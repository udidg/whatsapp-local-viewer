#!/usr/bin/env python3
"""
WhatsApp Chat Viewer
====================
Converts a WhatsApp exported .zip file (including media) into a standalone
HTML file that renders the chat thread with a WhatsApp-like UI.

Usage:
    python whatsapp_viewer.py <path_to_export.zip>

The script will:
1. Extract the zip into a folder named after the chat (alongside the zip).
2. Parse _chat.txt (supports both iOS and Android export formats).
3. Generate an HTML file with the same base name as the zip file.
"""

import argparse
import html
import json
import os
import re
import sys
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# ─── Constants ───────────────────────────────────────────────────────────────

# iOS format:    [DD/MM/YYYY, HH:MM:SS] Sender: message
IOS_MSG_RE = re.compile(
    r"^\u200e?\[(\d{1,2}/\d{1,2}/\d{4}), (\d{1,2}:\d{2}:\d{2})\] ([^:]+): (.*)$",
    re.DOTALL,
)

# Android format: DD/MM/YYYY, HH:MM - Sender: message
ANDROID_MSG_RE = re.compile(
    r"^\u200e?(\d{1,2}/\d{1,2}/\d{4}), (\d{1,2}:\d{2}) - ([^:]+): (.*)$",
    re.DOTALL,
)

# iOS system event (no sender colon pair):  [date, time] Text
IOS_SYS_RE = re.compile(
    r"^\u200e?\[(\d{1,2}/\d{1,2}/\d{4}), (\d{1,2}:\d{2}:\d{2})\] (.+)$",
    re.DOTALL,
)

# Android system event: date, time - Text
ANDROID_SYS_RE = re.compile(
    r"^\u200e?(\d{1,2}/\d{1,2}/\d{4}), (\d{1,2}:\d{2}) - (.+)$",
    re.DOTALL,
)

ATTACHED_RE = re.compile(r"^<attached:\s*(.+)>\s*$")

MEDIA_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp",  # images
    ".mp4", ".mov", ".avi", ".mkv",                    # video
    ".mp3", ".ogg", ".opus", ".m4a", ".aac",           # audio
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",          # documents
    ".vcf",                                             # contact
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
AUDIO_EXTENSIONS = {".mp3", ".ogg", ".opus", ".m4a", ".aac"}
DOC_EXTENSIONS   = {".pdf", ".doc", ".docx", ".xls", ".xlsx"}


# ─── Colour palette for senders ──────────────────────────────────────────────

SENDER_COLORS = [
    "#E74C3C", "#8E44AD", "#2980B9", "#27AE60",
    "#F39C12", "#16A085", "#C0392B", "#2471A3",
    "#1E8449", "#D35400", "#7D3C98", "#117A65",
    "#B7950B", "#1A5276", "#6E2F1A",
]


def sender_color(name: str, palette: dict) -> str:
    if name not in palette:
        palette[name] = SENDER_COLORS[len(palette) % len(SENDER_COLORS)]
    return palette[name]


def initials(name: str) -> str:
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return name[:2].upper() if len(name) >= 2 else name[0].upper()


# ─── Parsing ─────────────────────────────────────────────────────────────────

def detect_format(lines: list[str]) -> str:
    """Return 'ios', 'android', or raise ValueError."""
    for line in lines[:50]:
        line = line.strip()
        if IOS_MSG_RE.match(line) or IOS_SYS_RE.match(line):
            return "ios"
        if ANDROID_MSG_RE.match(line) or ANDROID_SYS_RE.match(line):
            return "android"
    raise ValueError("Cannot detect WhatsApp export format (iOS or Android).")


def parse_chat(raw_text: str) -> list[dict]:
    """
    Parse the raw chat text into a list of message dicts:
      {
        "type":    "message" | "system",
        "date":    datetime,
        "sender":  str,         # only for type==message
        "text":    str,
        "media":   str | None,  # filename inside extract dir, or None
      }
    """
    # Normalise line endings; strip BOM/RTL markers from line starts
    raw_text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = raw_text.split("\n")

    fmt = detect_format(lines)

    if fmt == "ios":
        new_msg_re  = IOS_MSG_RE
        new_sys_re  = IOS_SYS_RE
        date_fmt    = "%d/%m/%Y %H:%M:%S"
    else:
        new_msg_re  = ANDROID_MSG_RE
        new_sys_re  = ANDROID_SYS_RE
        date_fmt    = "%d/%m/%Y %H:%M"

    messages: list[dict] = []
    current: dict | None = None

    def flush(msg):
        if msg is None:
            return
        text = msg["text"].strip()
        # Strip leading zero-width / RTL markers
        text = text.lstrip("\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2068\u2069")
        # Check for attachment
        m = ATTACHED_RE.match(text)
        if m:
            msg["media"] = m.group(1).strip()
            msg["text"]  = ""
        else:
            msg["media"] = None
            msg["text"]  = text
        messages.append(msg)

    for line in lines:
        # Strip leading RTL/LRM markers from line itself
        stripped = line.lstrip("\u200e\u200f\u202a\u202b\u202c\u202d\u202e")

        m = new_msg_re.match(stripped)
        if m:
            flush(current)
            date_str, time_str, sender, text = m.groups()
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", date_fmt)
            except ValueError:
                dt = None
            current = {
                "type":   "message",
                "date":   dt,
                "sender": sender.strip(),
                "text":   text,
                "media":  None,
            }
            continue

        m2 = new_sys_re.match(stripped)
        if m2:
            flush(current)
            date_str, time_str, text = m2.groups()
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", date_fmt)
            except ValueError:
                dt = None
            current = {
                "type":   "system",
                "date":   dt,
                "sender": "",
                "text":   text.strip(),
                "media":  None,
            }
            continue

        # Continuation line (multi-line message)
        if current is not None:
            current["text"] += "\n" + line

    flush(current)
    return messages


# ─── HTML generation ─────────────────────────────────────────────────────────

def media_html(filename: str, media_dir_rel: str) -> str:
    """Return HTML snippet for a media file, given relative path from html file."""
    ext = Path(filename).suffix.lower()
    # Build a relative path from the HTML file to the media directory
    rel_path = html.escape(f"{media_dir_rel}/{filename}")
    safe_name = html.escape(filename)

    if ext in IMAGE_EXTENSIONS:
        return (
            f'<a href="{rel_path}" target="_blank">'
            f'<img class="media-img" src="{rel_path}" alt="{safe_name}" loading="lazy">'
            f'</a>'
        )
    if ext in VIDEO_EXTENSIONS:
        return (
            f'<video class="media-video" controls preload="metadata">'
            f'<source src="{rel_path}">'
            f'Your browser does not support video.'
            f'</video>'
        )
    if ext in AUDIO_EXTENSIONS:
        return (
            f'<audio class="media-audio" controls preload="metadata">'
            f'<source src="{rel_path}">'
            f'Your browser does not support audio.'
            f'</audio>'
        )
    # Document / unknown
    icon = "📄"
    if ext == ".pdf":
        icon = "📕"
    elif ext == ".vcf":
        icon = "👤"
    return (
        f'<a class="media-doc" href="{rel_path}" target="_blank" download="{safe_name}">'
        f'{icon} {safe_name}'
        f'</a>'
    )


def text_to_html(text: str) -> str:
    """Convert plain WhatsApp message text to safe HTML with basic formatting."""
    if not text:
        return ""
    # Escape HTML first
    t = html.escape(text)
    # WhatsApp bold (*text*), italic (_text_), strike (~text~), mono (```text```)
    t = re.sub(r"\*([^*\n]+)\*",    r"<strong>\1</strong>", t)
    t = re.sub(r"_([^_\n]+)_",      r"<em>\1</em>",         t)
    t = re.sub(r"~([^~\n]+)~",      r"<del>\1</del>",        t)
    t = re.sub(r"```(.+?)```",       r"<code>\1</code>",      t, flags=re.DOTALL)
    # URLs
    t = re.sub(
        r"(https?://[^\s<>\"']+)",
        r'<a href="\1" target="_blank" rel="noopener">\1</a>',
        t,
    )
    # Newlines → <br>
    t = t.replace("\n", "<br>")
    return t


_VIEWER_JS = '''/**
 * viewer.js — WhatsApp Local Viewer rendering engine
 * Loaded by both index.html (standalone) and Python-generated per-chat HTML.
 *
 * Entry point:
 *   window.WA.init(config)
 *
 * config = {
 *   rows      : Array,   // parsed row objects (see below)
 *   palette   : Object,  // { senderName: "#hexcolor", ... }
 *   totalMsgs : Number,
 *   chatName  : String,
 *   mediaBase : String,  // relative path prefix for media files ('' for standalone)
 *   getMediaUrl: Function|null, // (filename) => objectURL  — used by standalone mode
 * }
 *
 * Row object kinds:
 *   { kind:'date',    date:'YYYY-MM-DD', label:'3 September 2023' }
 *   { kind:'system',  text:'...' }
 *   { kind:'message', sender, color, inits, time, date,
 *                     text_html, media_html, media_file,
 *                     media_type, show_name, searchable }
 *
 * media_type: 'image'|'video'|'audio'|'doc'|'contact'|null
 */

(function (global) {
  'use strict';

  /* ══════════════════════════════════════════════════════════════════════════
     CSS  (injected once into <head>)
     ══════════════════════════════════════════════════════════════════════════ */
  const CSS = `
:root {
  --bg-app:        #ECE5DD;
  --bg-header:     #128C7E;
  --bg-toolbar:    #f0f0f0;
  --bg-bubble:     #ffffff;
  --bg-date-sep:   #D9F7BE;
  --bg-sys:        rgba(255,255,255,.75);
  --bg-stats:      #ffffff;
  --bg-input:      #ffffff;
  --border:        #cccccc;
  --text-main:     #111111;
  --text-muted:    #555555;
  --text-time:     #999999;
  --text-header:   #ffffff;
  --shadow-bubble: rgba(0,0,0,.13);
  --mark-bg:       #FFD700;
  --scrollbar:     #bbbbbb;
  --stat-bar-bg:   #e0e0e0;
  --safe-bottom:   env(safe-area-inset-bottom, 0px);
  --safe-left:     env(safe-area-inset-left,   0px);
  --safe-right:    env(safe-area-inset-right,  0px);
}
body.dark {
  --bg-app:        #0d1418;
  --bg-header:     #1f2c34;
  --bg-toolbar:    #1f2c34;
  --bg-bubble:     #202c33;
  --bg-date-sep:   #1d2b22;
  --bg-sys:        rgba(32,44,51,.85);
  --bg-stats:      #111b21;
  --bg-input:      #2a3942;
  --border:        #2a3942;
  --text-main:     #e9edef;
  --text-muted:    #8696a0;
  --text-time:     #8696a0;
  --text-header:   #e9edef;
  --shadow-bubble: rgba(0,0,0,.4);
  --mark-bg:       #b8860b;
  --scrollbar:     #2a3942;
  --stat-bar-bg:   #2a3942;
}
*,*::before,*::after { box-sizing:border-box; margin:0; padding:0; }
html { height:100%; }
body {
  height:100%; display:flex; flex-direction:column;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;
  font-size:14px;
  background:var(--bg-app); color:var(--text-main);
  overflow:hidden;
  padding-left:var(--safe-left); padding-right:var(--safe-right);
}

/* ── Header ── */
#wa-header {
  display:flex; align-items:center; gap:10px;
  background:var(--bg-header); color:var(--text-header);
  padding:10px 14px;
  padding-top:max(10px, env(safe-area-inset-top,10px));
  flex-shrink:0; box-shadow:0 1px 3px rgba(0,0,0,.3);
  -webkit-tap-highlight-color:transparent;
}
#wa-header .wa-chat-avatar {
  width:38px; height:38px; border-radius:50%;
  background:#25D366; display:flex; align-items:center; justify-content:center;
  font-weight:700; font-size:15px; color:#fff; flex-shrink:0; user-select:none;
}
#wa-header h1 {
  font-size:15px; font-weight:600; flex:1;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}
.wa-header-actions { display:flex; align-items:center; gap:4px; flex-shrink:0; }
#wa-msg-count { font-size:11px; opacity:.8; white-space:nowrap; }

/* ── Icon buttons ── */
.wa-icon-btn {
  background:none; border:none; cursor:pointer;
  color:var(--text-header); font-size:20px;
  padding:6px 8px; border-radius:8px; line-height:1; opacity:.85;
  min-width:40px; min-height:40px;
  display:flex; align-items:center; justify-content:center;
  -webkit-tap-highlight-color:transparent;
  transition:opacity .15s,background .15s;
}
.wa-icon-btn:hover  { opacity:1; background:rgba(255,255,255,.15); }
.wa-icon-btn:active { opacity:1; background:rgba(255,255,255,.25); }

/* ── Toolbar ── */
#wa-toolbar {
  display:flex; align-items:center; gap:6px; flex-wrap:wrap;
  background:var(--bg-toolbar); padding:6px 12px; flex-shrink:0;
  border-bottom:1px solid var(--border);
}
#wa-search-row { display:flex; align-items:center; gap:6px; width:100%; }
#wa-toolbar-filters { display:flex; align-items:center; gap:6px; flex-wrap:wrap; width:100%; }
#wa-toolbar-filters.collapsed { display:none; }
#wa-search-input {
  flex:1; border:1px solid var(--border); border-radius:20px;
  padding:8px 14px; font-size:14px; outline:none;
  background:var(--bg-input); color:var(--text-main);
  -webkit-appearance:none;
}
#wa-search-input:focus { border-color:#128C7E; }
#wa-match-count { font-size:12px; color:var(--text-muted); white-space:nowrap; }
#wa-filter-toggle {
  background:var(--bg-input); border:1px solid var(--border); border-radius:8px;
  padding:7px 10px; font-size:18px; cursor:pointer; line-height:1;
  color:var(--text-muted);
  min-width:40px; min-height:40px;
  display:flex; align-items:center; justify-content:center;
  -webkit-tap-highlight-color:transparent;
}
#wa-filter-toggle.active { border-color:#128C7E; color:#128C7E; }
.wa-toolbar-select,.wa-toolbar-date {
  border:1px solid var(--border); border-radius:8px;
  padding:7px 10px; font-size:13px; outline:none;
  background:var(--bg-input); color:var(--text-main); cursor:pointer;
  min-height:38px; -webkit-appearance:none; appearance:none;
}
.wa-toolbar-select {
  padding-right:28px;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8'%3E%3Cpath d='M0 0l6 8 6-8z' fill='%23888'/%3E%3C/svg%3E");
  background-repeat:no-repeat; background-position:right 10px center;
}
.wa-toolbar-select:focus,.wa-toolbar-date:focus { border-color:#128C7E; }
#wa-jump-btn {
  padding:7px 14px; border-radius:8px; border:none;
  background:#128C7E; color:#fff; font-size:13px;
  cursor:pointer; font-weight:600; min-height:38px;
  -webkit-tap-highlight-color:transparent;
}
#wa-jump-btn:active { background:#0e7065; }

/* ── Chat window ── */
#wa-chat {
  flex:1; overflow-y:auto; overflow-x:hidden;
  padding:8px 12px;
  padding-bottom:max(8px, env(safe-area-inset-bottom,8px));
  -webkit-overflow-scrolling:touch;
  overscroll-behavior:contain;
  /* Prevent scroll-position jumps during virtual renders */
  scroll-behavior:auto;
  contain:strict;
}
#wa-vlist {
  display:flex; flex-direction:column; gap:2px;
  /* min-height prevents collapse during renders */
  min-height:1px;
}
#wa-spacer-top,#wa-spacer-bottom { width:100%; flex-shrink:0; }

/* ── Date separator ── */
.wa-date-sep {
  display:flex; align-items:center; justify-content:center; margin:10px 0;
}
.wa-date-sep span {
  background:var(--bg-date-sep); color:var(--text-muted); font-size:12px;
  padding:3px 12px; border-radius:8px;
  box-shadow:0 1px 2px rgba(0,0,0,.15); user-select:none;
}

/* ── System message ── */
.wa-sys-msg {
  text-align:center; font-size:12px; color:var(--text-muted);
  background:var(--bg-sys); border-radius:8px;
  padding:4px 12px; margin:4px auto; max-width:88%;
}

/* ── Message row ── */
.wa-msg-row {
  display:flex; align-items:flex-end; gap:6px;
  max-width:85%; align-self:flex-start; margin-bottom:2px;
  /* Fixed min-height prevents layout shift during image load */
  min-height:44px;
  contain:layout style;
}
@media (min-width:600px) {
  .wa-msg-row { max-width:72%; }
  #wa-chat { padding:12px 20px; }
}

/* ── Avatar ── */
.wa-avatar {
  width:30px; height:30px; border-radius:50%; flex-shrink:0;
  display:flex; align-items:center; justify-content:center;
  font-size:11px; font-weight:700; color:#fff; user-select:none;
  align-self:flex-end;
}
@media (min-width:600px) { .wa-avatar { width:34px; height:34px; font-size:12px; } }

/* ── Bubble ── */
.wa-bubble {
  background:var(--bg-bubble); border-radius:8px 8px 8px 0;
  padding:6px 8px 4px; box-shadow:0 1px 1px var(--shadow-bubble);
  max-width:100%; min-width:60px;
  word-break:break-word; overflow-wrap:anywhere;
}

/* ── Sender name ── */
.wa-sender-name { font-size:12px; font-weight:700; margin-bottom:2px; }

/* ── Text ── */
.wa-msg-text { font-size:14px; line-height:1.5; white-space:pre-wrap; }

/* ── Timestamp ── */
.wa-msg-time { font-size:11px; color:var(--text-time); text-align:right; margin-top:3px; }

/* ── Media ── */
.wa-media-wrap { margin-bottom:4px; }
.wa-media-img {
  max-width:min(260px,100%); max-height:260px; border-radius:6px;
  display:block; cursor:pointer; object-fit:contain;
  /* Avoid layout shift: reserve space until loaded */
  background:var(--border); min-height:60px;
}
.wa-media-img.loaded { min-height:unset; background:none; }

/* ── Video with poster frame ── */
.wa-video-wrap {
  position:relative; display:inline-block;
  max-width:min(260px,100%); border-radius:6px; overflow:hidden;
  background:#000; cursor:pointer;
}
.wa-video-wrap video {
  display:block; width:100%; max-width:min(260px,100%);
  border-radius:6px;
}
.wa-video-thumb {
  display:block; width:100%; max-width:min(260px,100%);
  border-radius:6px; object-fit:cover; max-height:200px;
  background:var(--border); min-height:60px;
}
.wa-play-btn {
  position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
  width:48px; height:48px; border-radius:50%;
  background:rgba(0,0,0,.55); display:flex; align-items:center; justify-content:center;
  pointer-events:none;
}
.wa-play-btn::after {
  content:''; border:0 solid transparent;
  border-top:11px solid transparent;
  border-bottom:11px solid transparent;
  border-left:18px solid #fff;
  margin-left:4px;
}
.wa-video-wrap.playing video { display:block; }
.wa-video-wrap.playing .wa-video-thumb,
.wa-video-wrap.playing .wa-play-btn { display:none; }

.wa-media-audio { max-width:100%; width:240px; display:block; }
.wa-media-doc {
  display:inline-flex; align-items:center; gap:6px;
  background:var(--bg-toolbar); border-radius:8px;
  padding:8px 12px; text-decoration:none; color:var(--text-main);
  font-size:13px; border:1px solid var(--border);
  max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}

/* ── Search highlight ── */
mark { background:var(--mark-bg); border-radius:2px; padding:0 1px; }

/* ── Scrollbar ── */
#wa-chat::-webkit-scrollbar { width:4px; }
#wa-chat::-webkit-scrollbar-thumb { background:var(--scrollbar); border-radius:2px; }

/* ═══ Stats panel ═══ */
#wa-stats-overlay {
  position:fixed; inset:0; background:rgba(0,0,0,.4);
  z-index:200; display:none;
}
#wa-stats-overlay.open { display:block; }
#wa-stats-panel {
  position:absolute; top:0; right:0; bottom:0;
  background:var(--bg-stats); width:320px; max-width:100vw;
  overflow-y:auto; display:flex; flex-direction:column;
  box-shadow:-4px 0 20px rgba(0,0,0,.3);
}
@media (max-width:400px) { #wa-stats-panel { width:100vw; } }
#wa-stats-header {
  background:var(--bg-header); color:var(--text-header);
  padding:14px 16px;
  padding-top:max(14px,env(safe-area-inset-top,14px));
  display:flex; align-items:center; gap:10px;
  font-size:15px; font-weight:600; flex-shrink:0;
}
#wa-stats-close {
  margin-left:auto; background:none; border:none; cursor:pointer;
  color:var(--text-header); font-size:24px; line-height:1;
  padding:4px 8px; min-width:40px; min-height:40px;
  display:flex; align-items:center; justify-content:center;
}
#wa-stats-summary {
  padding:10px 16px; font-size:13px; color:var(--text-muted);
  border-bottom:1px solid var(--border); flex-shrink:0;
}
#wa-stats-list { padding:8px 0; flex:1; }
.wa-stat-row {
  display:flex; align-items:center; gap:10px;
  padding:10px 16px; cursor:pointer; min-height:56px;
  transition:background .1s;
}
.wa-stat-row:hover  { background:rgba(128,128,128,.08); }
.wa-stat-row.active { background:rgba(18,140,126,.12); }
.wa-stat-avatar {
  width:38px; height:38px; border-radius:50%; flex-shrink:0;
  display:flex; align-items:center; justify-content:center;
  font-size:13px; font-weight:700; color:#fff; user-select:none;
}
.wa-stat-info { flex:1; min-width:0; }
.wa-stat-name {
  font-size:13px; font-weight:600; white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; color:var(--text-main);
}
.wa-stat-bar-wrap {
  height:4px; background:var(--stat-bar-bg); border-radius:2px;
  margin-top:5px; overflow:hidden;
}
.wa-stat-bar  { height:100%; border-radius:2px; width:0; }
.wa-stat-nums { text-align:right; flex-shrink:0; }
.wa-stat-msg-count   { display:block; font-size:14px; font-weight:700; color:var(--text-main); }
.wa-stat-media-count { display:block; font-size:11px; color:var(--text-muted); }
`;

  /* ══════════════════════════════════════════════════════════════════════════
     HELPERS
     ══════════════════════════════════════════════════════════════════════════ */
  function esc(s) {
    return String(s)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;');
  }

  function initials(name) {
    const parts = String(name).trim().split(/\\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length-1][0]).toUpperCase();
    return name.slice(0,2).toUpperCase();
  }

  function escapeRegex(s) {
    return s.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
  }

  /* ══════════════════════════════════════════════════════════════════════════
     MEDIA HTML BUILDER
     Used both at parse time (Python path mode) and runtime (standalone mode).
     ══════════════════════════════════════════════════════════════════════════ */
  function buildMediaHTML(filename, url, mediaType) {
    const safeUrl  = esc(url);
    const safeName = esc(filename);

    if (mediaType === 'image') {
      return `<a href="${safeUrl}" target="_blank" rel="noopener">` +
             `<img class="wa-media-img" src="${safeUrl}" alt="${safeName}" loading="lazy" ` +
             `onload="this.classList.add('loaded')"></a>`;
    }
    if (mediaType === 'video') {
      // poster is generated at runtime by captureVideoFrame(); placeholder for now
      return `<div class="wa-video-wrap" data-src="${safeUrl}" onclick="WA._playVideo(this)">` +
             `<img class="wa-video-thumb" src="" alt="Video" data-video-src="${safeUrl}">` +
             `<div class="wa-play-btn"></div>` +
             `<video preload="none" controls style="display:none">` +
             `<source src="${safeUrl}"></video></div>`;
    }
    if (mediaType === 'audio') {
      return `<audio class="wa-media-audio" controls preload="metadata">` +
             `<source src="${safeUrl}"></audio>`;
    }
    // doc / contact
    const icon = filename.endsWith('.pdf') ? '📕'
               : filename.endsWith('.vcf') ? '👤' : '📄';
    return `<a class="wa-media-doc" href="${safeUrl}" target="_blank" download="${safeName}">` +
           `${icon} ${safeName}</a>`;
  }

  /* ══════════════════════════════════════════════════════════════════════════
     VIDEO POSTER FRAME CAPTURE
     ══════════════════════════════════════════════════════════════════════════ */
  function captureVideoFrame(videoWrap) {
    const thumb = videoWrap.querySelector('.wa-video-thumb');
    if (!thumb || thumb.src) return; // already captured or no thumb
    const src = thumb.dataset.videoSrc;
    if (!src) return;

    const vid = document.createElement('video');
    vid.muted = true;
    vid.playsInline = true;
    vid.preload = 'metadata';
    vid.src = src;
    vid.addEventListener('loadeddata', function onLoaded() {
      vid.removeEventListener('loadeddata', onLoaded);
      vid.currentTime = 0;
    });
    vid.addEventListener('seeked', function onSeeked() {
      vid.removeEventListener('seeked', onSeeked);
      try {
        const canvas = document.createElement('canvas');
        canvas.width  = Math.min(vid.videoWidth,  520);
        canvas.height = Math.min(vid.videoHeight, 400);
        const ratio = Math.min(canvas.width/vid.videoWidth, canvas.height/vid.videoHeight);
        canvas.width  = Math.round(vid.videoWidth  * ratio);
        canvas.height = Math.round(vid.videoHeight * ratio);
        canvas.getContext('2d').drawImage(vid, 0, 0, canvas.width, canvas.height);
        thumb.src = canvas.toDataURL('image/jpeg', 0.7);
        thumb.classList.add('loaded');
      } catch(e) {
        // cross-origin or security error — leave blank thumb
      }
      vid.src = '';
    }, { once: true });
    vid.load();
  }

  /* Expose for inline onclick */
  function playVideo(wrap) {
    if (wrap.classList.contains('playing')) return;
    wrap.classList.add('playing');
    const vid = wrap.querySelector('video');
    if (vid) { vid.style.display = 'block'; vid.play(); }
  }

  /* ══════════════════════════════════════════════════════════════════════════
     MAIN INIT
     ══════════════════════════════════════════════════════════════════════════ */
  function init(cfg) {
    const {
      rows, palette, totalMsgs, chatName,
      mediaBase,    // e.g. "WhatsApp Chat - X/" — used in Python mode
      getMediaUrl,  // function(filename) => url — used in standalone mode
    } = cfg;

    /* ── Inject CSS ── */
    if (!document.getElementById('wa-styles')) {
      const style = document.createElement('style');
      style.id = 'wa-styles';
      style.textContent = CSS;
      document.head.appendChild(style);
    }

    /* ── Resolve URL for a media filename ── */
    function mediaUrl(filename) {
      if (getMediaUrl) return getMediaUrl(filename);
      return (mediaBase ? mediaBase + '/' : '') + filename;
    }

    /* ── Build DOM skeleton ── */
    document.body.innerHTML = '';

    /* ─ Stats data ─ */
    const senderMsgCount   = {};
    const senderMediaCount = {};
    rows.forEach(r => {
      if (r.kind !== 'message') return;
      senderMsgCount[r.sender]   = (senderMsgCount[r.sender]   || 0) + 1;
      if (r.media_file)
        senderMediaCount[r.sender] = (senderMediaCount[r.sender] || 0) + 1;
    });
    const sortedSenders = Object.keys(senderMsgCount)
      .sort((a,b) => senderMsgCount[b] - senderMsgCount[a]);

    /* ─ Sender filter options ─ */
    const senderOptions = ['<option value="">All senders</option>',
      ...sortedSenders.map(s => `<option value="${esc(s)}">${esc(s)}</option>`)
    ].join('');

    /* ─ Date range ─ */
    const allDates = [...new Set(
      rows.filter(r => r.date).map(r => r.date)
    )].sort();
    const dateMin = allDates[0]  || '';
    const dateMax = allDates[allDates.length-1] || '';

    /* ─ Stats rows ─ */
    const maxCount = Math.max(1, ...sortedSenders.map(s => senderMsgCount[s]));
    const statsRowsHTML = sortedSenders.map(s => {
      const c    = palette[s] || '#555';
      const pct  = (senderMsgCount[s] / maxCount * 100).toFixed(1);
      return `<div class="wa-stat-row" data-sender="${esc(s)}">
        <div class="wa-stat-avatar" style="background:${c}">${esc(initials(s))}</div>
        <div class="wa-stat-info">
          <div class="wa-stat-name">${esc(s)}</div>
          <div class="wa-stat-bar-wrap">
            <div class="wa-stat-bar" style="background:${c};width:${pct}%"></div>
          </div>
        </div>
        <div class="wa-stat-nums">
          <span class="wa-stat-msg-count">${senderMsgCount[s]}</span>
          <span class="wa-stat-media-count">${senderMediaCount[s]||0} media</span>
        </div>
      </div>`;
    }).join('');

    const chatInits = esc(initials(chatName));
    const chatNameEsc = esc(chatName);

    document.body.innerHTML = `
<div id="wa-header">
  <div class="wa-chat-avatar">${chatInits}</div>
  <h1>${chatNameEsc}</h1>
  <div class="wa-header-actions">
    <span id="wa-msg-count"></span>
    <button class="wa-icon-btn" id="wa-stats-btn" title="Sender stats" aria-label="Sender stats">📊</button>
    <button class="wa-icon-btn" id="wa-dark-btn"  title="Toggle dark mode" aria-label="Toggle dark mode">🌙</button>
  </div>
</div>
<div id="wa-toolbar">
  <div id="wa-search-row">
    <input type="search" id="wa-search-input" placeholder="Search… ( / )" autocomplete="off" aria-label="Search messages">
    <button id="wa-filter-toggle" title="Filters" aria-expanded="false">🔍</button>
    <span id="wa-match-count"></span>
  </div>
  <div id="wa-toolbar-filters" class="collapsed">
    <select class="wa-toolbar-select" id="wa-sender-filter" aria-label="Filter by sender">${senderOptions}</select>
    <input type="date" class="wa-toolbar-date" id="wa-date-picker" min="${dateMin}" max="${dateMax}" aria-label="Jump to date">
    <button id="wa-jump-btn">Go</button>
  </div>
</div>
<div id="wa-chat" role="log" aria-live="off">
  <div id="wa-spacer-top"></div>
  <div id="wa-vlist"></div>
  <div id="wa-spacer-bottom"></div>
</div>
<div id="wa-stats-overlay" role="dialog" aria-modal="true" aria-label="Sender stats">
  <div id="wa-stats-panel">
    <div id="wa-stats-header">
      📊 Sender Stats
      <button id="wa-stats-close" aria-label="Close">&times;</button>
    </div>
    <div id="wa-stats-summary"></div>
    <div id="wa-stats-list">${statsRowsHTML}</div>
  </div>
</div>`;

    /* ── Element refs ── */
    const chatEl        = document.getElementById('wa-chat');
    const vlist         = document.getElementById('wa-vlist');
    const spacerTop     = document.getElementById('wa-spacer-top');
    const spacerBot     = document.getElementById('wa-spacer-bottom');
    const searchInput   = document.getElementById('wa-search-input');
    const matchCountEl  = document.getElementById('wa-match-count');
    const msgCountEl    = document.getElementById('wa-msg-count');
    const senderSel     = document.getElementById('wa-sender-filter');
    const datePicker    = document.getElementById('wa-date-picker');
    const jumpBtn       = document.getElementById('wa-jump-btn');
    const darkBtn       = document.getElementById('wa-dark-btn');
    const statsBtn      = document.getElementById('wa-stats-btn');
    const statsOverlay  = document.getElementById('wa-stats-overlay');
    const statsClose    = document.getElementById('wa-stats-close');
    const statsSummary  = document.getElementById('wa-stats-summary');
    const filterToggle  = document.getElementById('wa-filter-toggle');
    const filterPanel   = document.getElementById('wa-toolbar-filters');

    msgCountEl.textContent = totalMsgs.toLocaleString() + ' msgs';
    statsSummary.textContent =
      totalMsgs.toLocaleString() + ' messages · ' +
      sortedSenders.length + ' participants';

    /* ════════════════════════════════════════════════════════════════════════
       DARK MODE
       ════════════════════════════════════════════════════════════════════════ */
    function applyDark(on) {
      document.body.classList.toggle('dark', on);
      darkBtn.textContent = on ? '☀️' : '🌙';
      try { localStorage.setItem('wa-dark', on ? '1' : '0'); } catch(_) {}
    }
    (function() {
      let saved; try { saved = localStorage.getItem('wa-dark'); } catch(_) {}
      applyDark(saved !== null ? saved === '1'
        : window.matchMedia('(prefers-color-scheme: dark)').matches);
    })();
    darkBtn.addEventListener('click', () => applyDark(!document.body.classList.contains('dark')));

    /* ════════════════════════════════════════════════════════════════════════
       FILTER TOGGLE
       ════════════════════════════════════════════════════════════════════════ */
    filterToggle.addEventListener('click', () => {
      const col = filterPanel.classList.toggle('collapsed');
      filterToggle.classList.toggle('active', !col);
      filterToggle.setAttribute('aria-expanded', String(!col));
    });

    /* ════════════════════════════════════════════════════════════════════════
       STATS PANEL
       ════════════════════════════════════════════════════════════════════════ */
    statsBtn.addEventListener('click',  () => statsOverlay.classList.add('open'));
    statsClose.addEventListener('click',() => statsOverlay.classList.remove('open'));
    statsOverlay.addEventListener('click', e => {
      if (e.target === statsOverlay) statsOverlay.classList.remove('open');
    });
    document.querySelectorAll('.wa-stat-row').forEach(row => {
      row.addEventListener('click', () => {
        senderSel.value = row.dataset.sender;
        statsOverlay.classList.remove('open');
        applyFilters();
      });
    });

    /* ════════════════════════════════════════════════════════════════════════
       VIRTUAL SCROLL
       ════════════════════════════════════════════════════════════════════════ */
    const PAGE     = 80;
    const OVERSCAN = 24;

    /* Per-row height cache — measured after first render, keyed by row index */
    const heightCache = new Map();
    let   defaultH    = 72;  // updated after first batch measurement

    let filtered   = rows.map((_, i) => i);
    let activeQ    = '';
    let activeSnd  = '';
    let winStart   = 0;
    let winEnd     = 0;

    /* ── Row HTML generator ── */
    function rowHTML(fi) {
      const r = rows[filtered[fi]];
      if (r.kind === 'date') {
        return `<div class="wa-date-sep" data-fi="${fi}" data-date="${r.date}">` +
               `<span>${esc(r.label)}</span></div>`;
      }
      if (r.kind === 'system') {
        return `<div class="wa-sys-msg" data-fi="${fi}">${esc(r.text)}</div>`;
      }

      /* message */
      const q   = activeQ;
      let txt   = r.text_html || '';
      if (q && txt) txt = txt.replace(new RegExp(`(${escapeRegex(q)})`, 'gi'), '<mark>$1</mark>');

      let mediaH = r.media_html || '';
      /* In standalone mode, media_html is empty; build it from media_file + getMediaUrl */
      if (!mediaH && r.media_file && getMediaUrl) {
        const url = getMediaUrl(r.media_file);
        if (url) mediaH = buildMediaHTML(r.media_file, url, r.media_type);
      }

      const namePart  = r.show_name
        ? `<div class="wa-sender-name" style="color:${r.color}">${esc(r.sender)}</div>` : '';
      const mediaPart = mediaH ? `<div class="wa-media-wrap">${mediaH}</div>` : '';
      const textPart  = txt    ? `<div class="wa-msg-text">${txt}</div>` : '';

      return `<div class="wa-msg-row" data-fi="${fi}">` +
        `<div class="wa-avatar" style="background:${r.color}" title="${esc(r.sender)}">${esc(r.inits)}</div>` +
        `<div class="wa-bubble">` +
          namePart + mediaPart + textPart +
          `<div class="wa-msg-time">${esc(r.time)}</div>` +
        `</div></div>`;
    }

    /* ── Spacer height from cache ── */
    function spacerHeight(fromFi, toFi) {
      let h = 0;
      for (let i = fromFi; i < toFi; i++) {
        h += heightCache.has(i) ? heightCache.get(i) : defaultH;
      }
      return h;
    }

    /* ── After each render, measure rows and update cache ── */
    function measureRendered() {
      const children = vlist.children;
      let totalH = 0, count = 0;
      for (const el of children) {
        const fi = parseInt(el.dataset.fi, 10);
        if (isNaN(fi)) continue;
        const h = el.offsetHeight + 2; // +2 for gap
        heightCache.set(fi, h);
        totalH += h; count++;
      }
      if (count > 10) defaultH = Math.round(totalH / count);
    }

    /* ── Capture video poster frames visible in current window ── */
    function captureVisibleVideos() {
      vlist.querySelectorAll('.wa-video-wrap').forEach(wrap => {
        captureVideoFrame(wrap);
      });
    }

    /* ── Core render ── */
    function renderWindow(centerFi, resetScroll) {
      const total = filtered.length;
      const start = Math.max(0, centerFi - OVERSCAN);
      const end   = Math.min(total, centerFi + PAGE + OVERSCAN);

      /* Measure current window before replacement (stabilise scroll) */
      const prevScrollTop = chatEl.scrollTop;

      /* Build HTML for new window */
      const parts = [];
      for (let i = start; i < end; i++) parts.push(rowHTML(i));

      /* Compute spacers BEFORE DOM change to minimise reflow cascade */
      const topH = spacerHeight(0, start);
      const botH = spacerHeight(end, total);

      /* Single DOM batch — prevents multiple reflows */
      spacerTop.style.height = topH + 'px';
      spacerBot.style.height = botH + 'px';
      vlist.innerHTML = parts.join('');

      winStart = start;
      winEnd   = end;

      if (resetScroll) {
        if (!activeQ && !activeSnd) {
          chatEl.scrollTop = chatEl.scrollHeight;
        } else {
          chatEl.scrollTop = 0;
        }
      } else {
        /* Restore scroll position — top spacer height changed so adjust */
        chatEl.scrollTop = prevScrollTop;
      }

      /* Measure & capture async so paint is not blocked */
      requestAnimationFrame(() => {
        measureRendered();
        captureVisibleVideos();
      });
    }

    /* ════════════════════════════════════════════════════════════════════════
       FILTERING
       ════════════════════════════════════════════════════════════════════════ */
    function applyFilters() {
      const q   = searchInput.value.trim().toLowerCase();
      const snd = senderSel.value;
      activeQ   = q;
      activeSnd = snd;

      filtered = [];
      for (let i = 0; i < rows.length; i++) {
        const r = rows[i];
        if (r.kind !== 'message') { filtered.push(i); continue; }
        if (snd && r.sender !== snd) continue;
        if (q && !r.searchable.includes(q) && !r.sender.toLowerCase().includes(q)) continue;
        filtered.push(i);
      }

      const msgMatched = filtered.filter(i => rows[i].kind === 'message').length;
      if (q || snd) {
        matchCountEl.textContent = msgMatched.toLocaleString() + ' results';
        msgCountEl.textContent   = msgMatched.toLocaleString() + ' / ' + totalMsgs.toLocaleString() + ' msgs';
      } else {
        matchCountEl.textContent = '';
        msgCountEl.textContent   = totalMsgs.toLocaleString() + ' msgs';
      }

      document.querySelectorAll('.wa-stat-row').forEach(r => {
        r.classList.toggle('active', r.dataset.sender === snd && snd !== '');
      });

      heightCache.clear();
      renderWindow(0, true);
    }

    searchInput.addEventListener('input', applyFilters);
    senderSel.addEventListener('change', applyFilters);

    /* ════════════════════════════════════════════════════════════════════════
       SCROLL HANDLER  — slides the window; uses rAF to avoid thrashing
       ════════════════════════════════════════════════════════════════════════ */
    let scrollRaf = null;
    chatEl.addEventListener('scroll', () => {
      if (scrollRaf) return;
      scrollRaf = requestAnimationFrame(() => {
        scrollRaf = null;
        const total     = filtered.length;
        const topH      = parseFloat(spacerTop.style.height) || 0;
        const relScroll = Math.max(0, chatEl.scrollTop - topH);
        /* Estimate current fi using average height */
        const estFi = winStart + Math.round(relScroll / defaultH);

        const nearTop = estFi < winStart + OVERSCAN && winStart > 0;
        const nearBot = estFi > winEnd   - OVERSCAN && winEnd   < total;

        if (nearTop) renderWindow(Math.max(0, estFi - Math.floor(PAGE/2)), false);
        else if (nearBot) renderWindow(Math.min(total - PAGE, estFi), false);
      });
    }, { passive: true });

    /* ════════════════════════════════════════════════════════════════════════
       JUMP TO DATE
       ════════════════════════════════════════════════════════════════════════ */
    function jumpToDate(iso) {
      if (!iso) return;
      let fi = -1;
      for (let i = 0; i < filtered.length; i++) {
        const r = rows[filtered[i]];
        if (r.kind === 'date' && r.date >= iso) { fi = i; break; }
      }
      if (fi === -1) fi = filtered.length - 1;
      if (fi < 0) return;
      renderWindow(fi, false);
      requestAnimationFrame(() => {
        const el = vlist.querySelector('.wa-date-sep');
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
        else chatEl.scrollTop = parseFloat(spacerTop.style.height) || 0;
      });
    }

    jumpBtn.addEventListener('click', () => jumpToDate(datePicker.value));
    datePicker.addEventListener('keydown', e => {
      if (e.key === 'Enter') jumpToDate(datePicker.value);
    });

    /* ════════════════════════════════════════════════════════════════════════
       KEYBOARD SHORTCUTS
       ════════════════════════════════════════════════════════════════════════ */
    document.addEventListener('keydown', e => {
      const tag = document.activeElement.tagName;
      const inInput = tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA';
      if (e.key === '/' && !inInput) { e.preventDefault(); searchInput.focus(); }
      if (e.key === 'Escape') {
        if (statsOverlay.classList.contains('open')) {
          statsOverlay.classList.remove('open');
        } else if (!filterPanel.classList.contains('collapsed')) {
          filterPanel.classList.add('collapsed');
          filterToggle.classList.remove('active');
        } else {
          searchInput.value = ''; senderSel.value = '';
          applyFilters(); searchInput.blur();
        }
      }
    });

    /* ── Initial render ── */
    renderWindow(Math.max(0, filtered.length - PAGE), false);
    chatEl.scrollTop = chatEl.scrollHeight;
  } /* end init() */

  /* ══════════════════════════════════════════════════════════════════════════
     PUBLIC API
     ══════════════════════════════════════════════════════════════════════════ */
  global.WA = {
    init,
    _playVideo: playVideo,
    _captureFrame: captureVideoFrame,
  };

})(window);
'''


def load_viewer_js() -> str:
    return _VIEWER_JS


def build_html(
    messages: list[dict],
    chat_name: str,
    media_dir_rel: str,
    available_media: set[str],
) -> str:
    """
    Build a fully self-contained HTML file.
    viewer.js and all chat data are inlined — no internet required.
    """

    color_palette: dict[str, str] = {}
    for msg in messages:
        if msg["type"] == "message" and msg["sender"]:
            sender_color(msg["sender"], color_palette)

    # ── Build row data array ──────────────────────────────────────────────────
    rows_data: list[dict] = []
    prev_date_label: str | None = None
    prev_sender:     str | None = None

    for msg in messages:
        dt: datetime | None = msg.get("date")
        date_label = dt.strftime("%-d %B %Y") if dt else ""
        date_iso   = dt.strftime("%Y-%m-%d")  if dt else ""
        time_label = dt.strftime("%H:%M")     if dt else ""

        if date_label and date_label != prev_date_label:
            rows_data.append({"kind": "date", "date": date_iso, "label": date_label})
            prev_date_label = date_label
            prev_sender     = None

        if msg["type"] == "system":
            t = msg["text"].strip()
            if t:
                rows_data.append({"kind": "system", "text": t})
            continue

        sender  = msg["sender"]
        color   = color_palette.get(sender, "#555")
        inits_v = initials(sender)
        text_h  = text_to_html(msg["text"])

        # media_html is built at render time; store filename + type for viewer.js
        media_file = msg.get("media") or ""
        mtype      = ""
        m_html     = ""
        if media_file and media_file in available_media:
            ext = Path(media_file).suffix.lower()
            if ext in IMAGE_EXTENSIONS:  mtype = "image"
            elif ext in VIDEO_EXTENSIONS: mtype = "video"
            elif ext in AUDIO_EXTENSIONS: mtype = "audio"
            elif ext in DOC_EXTENSIONS:   mtype = "doc"
            elif ext == ".vcf":           mtype = "contact"
            m_html = media_html(media_file, media_dir_rel)

        show_name   = (sender != prev_sender)
        prev_sender = sender

        rows_data.append({
            "kind":       "message",
            "sender":     sender,
            "color":      color,
            "inits":      inits_v,
            "time":       time_label,
            "date":       date_iso,
            "text_html":  text_h,
            "media_html": m_html,
            "media_file": media_file,
            "media_type": mtype,
            "show_name":  show_name,
            "searchable": (msg.get("text") or "").lower(),
        })

    rows_json      = json.dumps(rows_data, ensure_ascii=False)
    palette_json   = json.dumps(color_palette)
    total_messages = sum(1 for m in messages if m["type"] == "message")
    viewer_js      = load_viewer_js()

    # Build as a list of parts to avoid f-string escaping issues with JS braces
    parts = [
        "<!DOCTYPE html>\n",
        '<html lang="he" dir="auto">\n',
        "<head>\n",
        '<meta charset="utf-8">\n',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n',
        f"<title>{html.escape(chat_name)}</title>\n",
        "</head>\n",
        "<body>\n",
        "<script>\n",
        "window.__WA_CONFIG__ = {\n",
        f"  rows:      {rows_json},\n",
        f"  palette:   {palette_json},\n",
        f"  totalMsgs: {total_messages},\n",
        f"  chatName:  {json.dumps(chat_name)},\n",
        f"  mediaBase: {json.dumps(media_dir_rel)},\n",
        "  getMediaUrl: null\n",
        "};\n",
        "</script>\n",
        "<script>\n",
        viewer_js,
        "\n</script>\n",
        "<script>WA.init(window.__WA_CONFIG__);</script>\n",
        "</body>\n",
        "</html>\n",
    ]
    return "".join(parts)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert a WhatsApp exported ZIP to a local HTML viewer."
    )
    parser.add_argument("zip_path", help="Path to the WhatsApp export .zip file")
    args = parser.parse_args()

    zip_path = Path(args.zip_path).resolve()
    if not zip_path.exists():
        sys.exit(f"Error: file not found: {zip_path}")
    if not zipfile.is_zipfile(zip_path):
        sys.exit(f"Error: not a valid ZIP file: {zip_path}")

    # Derive chat name from the zip filename
    # e.g. "WhatsApp Chat - 🌳גן פיקוס🌳.zip" → "WhatsApp Chat - 🌳גן פיקוס🌳"
    chat_name = zip_path.stem
    if chat_name.lower().startswith("whatsapp chat - "):
        chat_name = chat_name[len("whatsapp chat - "):]
    if chat_name.lower().startswith("whatsapp chat with "):
        chat_name = chat_name[len("whatsapp chat with "):]

    zip_dir = zip_path.parent

    # Extract directory name = zip stem (no extension)
    extract_dir = zip_dir / zip_path.stem
    print(f"[1/4] Extracting '{zip_path.name}' → '{extract_dir.name}/'")
    extract_dir.mkdir(exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        # Extract all files; skip already-extracted ones to speed up reruns
        members = zf.infolist()
        for member in members:
            dest = extract_dir / member.filename
            if not dest.exists():
                zf.extract(member, extract_dir)
        available_media = set(zf.namelist())

    # Find chat text file
    chat_file_candidates = list(extract_dir.glob("_chat.txt")) + list(
        extract_dir.glob("*.txt")
    )
    if not chat_file_candidates:
        sys.exit("Error: no .txt chat file found inside the ZIP.")
    chat_file = chat_file_candidates[0]

    print(f"[2/4] Parsing '{chat_file.name}'…")
    raw_text = chat_file.read_text(encoding="utf-8", errors="replace")
    messages = parse_chat(raw_text)
    print(f"      {len(messages)} messages parsed.")

    # Relative path from the html file (placed in zip_dir) to extract_dir
    media_dir_rel = extract_dir.name  # just the folder name, since html is next to zip

    print(f"[3/4] Building HTML…")
    html_content = build_html(messages, chat_name, media_dir_rel, available_media)

    # Output HTML file: same base name as the zip, next to it
    html_path = zip_dir / (zip_path.stem + ".html")
    print(f"[4/4] Writing '{html_path.name}'…")
    html_path.write_text(html_content, encoding="utf-8")

    print(f"\nDone! Open in your browser:")
    print(f"  {html_path}")
    print(f"\nStats:")
    print(f"  Messages : {sum(1 for m in messages if m['type'] == 'message')}")
    print(f"  System   : {sum(1 for m in messages if m['type'] == 'system')}")
    print(f"  Media    : {sum(1 for m in messages if m.get('media'))}")
    senders = {m['sender'] for m in messages if m['type'] == 'message' and m['sender']}
    print(f"  Senders  : {len(senders)}")


if __name__ == "__main__":
    main()
