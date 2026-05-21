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


def build_html(
    messages: list[dict],
    chat_name: str,
    media_dir_rel: str,
    available_media: set[str],
) -> str:
    """Build the full HTML string."""

    color_palette: dict[str, str] = {}
    for msg in messages:
        if msg["type"] == "message" and msg["sender"]:
            sender_color(msg["sender"], color_palette)

    palette_json = json.dumps(color_palette)

    # ── Per-sender stats ─────────────────────────────────────────────────────
    sender_msg_counts:   dict[str, int] = {}
    sender_media_counts: dict[str, int] = {}
    for msg in messages:
        if msg["type"] != "message" or not msg["sender"]:
            continue
        s = msg["sender"]
        sender_msg_counts[s]   = sender_msg_counts.get(s, 0) + 1
        if msg.get("media"):
            sender_media_counts[s] = sender_media_counts.get(s, 0) + 1

    sorted_senders = sorted(sender_msg_counts, key=lambda s: sender_msg_counts[s], reverse=True)

    # Stats rows HTML (static — doesn't depend on virtual scroll)
    stats_rows_parts: list[str] = []
    for s in sorted_senders:
        c       = color_palette.get(s, "#555")
        inits_s = html.escape(initials(s))
        s_esc   = html.escape(s)
        msgs_n  = sender_msg_counts[s]
        media_n = sender_media_counts.get(s, 0)
        stats_rows_parts.append(
            f'<div class="stat-row" data-sender="{s_esc}">'
            f'<div class="stat-avatar" style="background:{c}">{inits_s}</div>'
            f'<div class="stat-info">'
            f'<div class="stat-name">{s_esc}</div>'
            f'<div class="stat-bar-wrap">'
            f'<div class="stat-bar" style="background:{c}" data-count="{msgs_n}"></div>'
            f'</div></div>'
            f'<div class="stat-nums">'
            f'<span class="stat-msg-count">{msgs_n}</span>'
            f'<span class="stat-media-count">{media_n} media</span>'
            f'</div></div>'
        )
    stats_rows_html = "\n".join(stats_rows_parts)

    # Sender filter options
    sender_options = '<option value="">All senders</option>\n'
    for s in sorted_senders:
        s_esc = html.escape(s)
        sender_options += f'<option value="{s_esc}">{s_esc}</option>\n'

    # Date range for picker
    all_dates = sorted({
        msg["date"].strftime("%Y-%m-%d")
        for msg in messages if msg.get("date")
    })
    date_min = all_dates[0]  if all_dates else ""
    date_max = all_dates[-1] if all_dates else ""

    # ── Build JSON data array for virtual scroll ──────────────────────────────
    # Each entry is a "row" object rendered by JS:
    #   { kind: "date",    date, label }
    #   { kind: "system",  text }
    #   { kind: "message", sender, color, inits, time, date,
    #                       text_html, media_html, show_name, searchable }
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
        m_html  = ""
        if msg.get("media") and msg["media"] in available_media:
            m_html = media_html(msg["media"], media_dir_rel)

        show_name   = (sender != prev_sender)
        prev_sender = sender
        searchable  = (msg.get("text") or "").lower()

        rows_data.append({
            "kind":       "message",
            "sender":     sender,
            "color":      color,
            "inits":      inits_v,
            "time":       time_label,
            "date":       date_iso,
            "text_html":  text_h,
            "media_html": m_html,
            "show_name":  show_name,
            "searchable": searchable,
        })

    rows_json      = json.dumps(rows_data, ensure_ascii=False)
    total_messages = sum(1 for m in messages if m["type"] == "message")

    return f"""<!DOCTYPE html>
<html lang="he" dir="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{html.escape(chat_name)}</title>
<style>
/* ── CSS variables ── */
:root {{
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
}}
body.dark {{
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
}}

/* ── Reset & Base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ height: 100%; }}
body {{
  height: 100%; display: flex; flex-direction: column;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto,
               Helvetica, Arial, sans-serif;
  font-size: 14px;
  background: var(--bg-app); color: var(--text-main);
  overflow: hidden;
  /* iOS full-screen */
  padding-left:  var(--safe-left);
  padding-right: var(--safe-right);
}}

/* ── Header ── */
#header {{
  display: flex; align-items: center; gap: 10px;
  background: var(--bg-header); color: var(--text-header);
  padding: 10px 14px;
  padding-top: max(10px, env(safe-area-inset-top, 10px));
  flex-shrink: 0;
  box-shadow: 0 1px 3px rgba(0,0,0,.3);
  -webkit-tap-highlight-color: transparent;
}}
#header .chat-avatar {{
  width: 38px; height: 38px; border-radius: 50%;
  background: #25D366; display: flex; align-items: center;
  justify-content: center; font-weight: 700; font-size: 15px; color: #fff;
  flex-shrink: 0; user-select: none;
}}
#header h1 {{
  font-size: 15px; font-weight: 600; flex: 1;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}}
.header-actions {{ display: flex; align-items: center; gap: 4px; flex-shrink: 0; }}
#msg-count {{ font-size: 11px; opacity: .8; white-space: nowrap; }}

/* ── Icon buttons ── */
.icon-btn {{
  background: none; border: none; cursor: pointer;
  color: var(--text-header); font-size: 20px;
  padding: 6px 8px; border-radius: 8px; line-height: 1;
  opacity: .85; transition: opacity .15s, background .15s;
  min-width: 40px; min-height: 40px;         /* touch target */
  display: flex; align-items: center; justify-content: center;
  -webkit-tap-highlight-color: transparent;
}}
.icon-btn:hover {{ opacity: 1; background: rgba(255,255,255,.15); }}
.icon-btn:active {{ opacity: 1; background: rgba(255,255,255,.25); }}

/* ── Toolbar ── */
#toolbar {{
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
  background: var(--bg-toolbar); padding: 6px 12px; flex-shrink: 0;
  border-bottom: 1px solid var(--border);
}}
/* On narrow screens collapse filters behind a toggle */
#toolbar-filters {{
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap; width: 100%;
}}
#toolbar-filters.collapsed {{ display: none; }}
#search-row {{
  display: flex; align-items: center; gap: 6px; width: 100%;
}}
#search-input {{
  flex: 1; border: 1px solid var(--border); border-radius: 20px;
  padding: 8px 14px; font-size: 14px; outline: none;
  background: var(--bg-input); color: var(--text-main);
  -webkit-appearance: none;
}}
#search-input:focus {{ border-color: #128C7E; }}
#match-count {{ font-size: 12px; color: var(--text-muted); white-space: nowrap; }}
#filter-toggle {{
  background: none; border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 10px; font-size: 18px; cursor: pointer; line-height: 1;
  color: var(--text-muted); background: var(--bg-input);
  min-width: 40px; min-height: 40px;
  display: flex; align-items: center; justify-content: center;
  -webkit-tap-highlight-color: transparent;
}}
#filter-toggle.active {{ border-color: #128C7E; color: #128C7E; }}

/* ── Sender filter & date picker ── */
.toolbar-select, .toolbar-date {{
  border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 10px; font-size: 13px; outline: none;
  background: var(--bg-input); color: var(--text-main); cursor: pointer;
  min-height: 38px; -webkit-appearance: none; appearance: none;
}}
.toolbar-select {{ padding-right: 28px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8'%3E%3Cpath d='M0 0l6 8 6-8z' fill='%23888'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 10px center;
}}
.toolbar-select:focus, .toolbar-date:focus {{ border-color: #128C7E; }}
#jump-btn {{
  padding: 7px 14px; border-radius: 8px; border: none;
  background: #128C7E; color: #fff; font-size: 13px;
  cursor: pointer; font-weight: 600; min-height: 38px;
  -webkit-tap-highlight-color: transparent;
}}
#jump-btn:active {{ background: #0e7065; }}

/* ── Chat window ── */
#chat {{
  flex: 1; overflow-y: auto; overflow-x: hidden;
  padding: 8px 12px;
  padding-bottom: max(8px, var(--safe-bottom));
  -webkit-overflow-scrolling: touch;
  overscroll-behavior: contain;
}}

/* ── Virtual scroll spacers ── */
#spacer-top, #spacer-bottom {{
  width: 100%; flex-shrink: 0;
}}

/* ── Date separator ── */
.date-sep {{
  display: flex; align-items: center; justify-content: center;
  margin: 10px 0;
}}
.date-sep span {{
  background: var(--bg-date-sep); color: var(--text-muted); font-size: 12px;
  padding: 3px 12px; border-radius: 8px;
  box-shadow: 0 1px 2px rgba(0,0,0,.15);
  user-select: none;
}}

/* ── System message ── */
.sys-msg {{
  text-align: center; font-size: 12px; color: var(--text-muted);
  background: var(--bg-sys); border-radius: 8px;
  padding: 4px 12px; margin: 4px auto; max-width: 88%;
}}

/* ── Message row ── */
.msg-row {{
  display: flex; align-items: flex-end; gap: 6px;
  max-width: 85%; align-self: flex-start; margin-bottom: 2px;
}}
@media (min-width: 600px) {{
  .msg-row {{ max-width: 72%; }}
  #chat {{ padding: 12px 20px; }}
}}

/* ── Avatar ── */
.avatar {{
  width: 30px; height: 30px; border-radius: 50%;
  flex-shrink: 0; display: flex; align-items: center;
  justify-content: center; font-size: 11px; font-weight: 700;
  color: #fff; user-select: none;
}}
@media (min-width: 600px) {{
  .avatar {{ width: 34px; height: 34px; font-size: 12px; }}
}}

/* ── Bubble ── */
.bubble {{
  background: var(--bg-bubble); border-radius: 8px 8px 8px 0;
  padding: 6px 8px 4px; box-shadow: 0 1px 1px var(--shadow-bubble);
  max-width: 100%; min-width: 60px;
  word-break: break-word; overflow-wrap: anywhere;
}}

/* ── Sender name inside bubble ── */
.sender-name {{ font-size: 12px; font-weight: 700; margin-bottom: 2px; }}

/* ── Message text ── */
.msg-text {{ font-size: 14px; line-height: 1.5; white-space: pre-wrap; }}

/* ── Timestamp ── */
.msg-time {{
  font-size: 11px; color: var(--text-time); text-align: right; margin-top: 3px;
}}

/* ── Media ── */
.media-wrap {{ margin-bottom: 4px; }}
.media-img {{
  max-width: min(260px, 100%); max-height: 260px; border-radius: 6px;
  display: block; cursor: pointer; object-fit: contain;
}}
.media-video {{
  max-width: min(260px, 100%); border-radius: 6px; display: block;
}}
.media-audio {{ max-width: 100%; width: 240px; display: block; }}
.media-doc {{
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--bg-toolbar); border-radius: 8px;
  padding: 8px 12px; text-decoration: none; color: var(--text-main);
  font-size: 13px; border: 1px solid var(--border); max-width: 100%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}

/* ── Search highlight ── */
mark {{ background: var(--mark-bg); border-radius: 2px; padding: 0 1px; }}

/* ── Scrollbar ── */
#chat::-webkit-scrollbar {{ width: 4px; }}
#chat::-webkit-scrollbar-thumb {{ background: var(--scrollbar); border-radius: 2px; }}

/* ═══ Stats panel (full-screen on mobile, side panel on desktop) ═══ */
#stats-overlay {{
  position: fixed; inset: 0; background: rgba(0,0,0,.4);
  z-index: 200; display: none;
}}
#stats-overlay.open {{ display: block; }}
#stats-panel {{
  position: absolute; top: 0; right: 0; bottom: 0;
  background: var(--bg-stats); width: 320px; max-width: 100vw;
  overflow-y: auto; display: flex; flex-direction: column;
  box-shadow: -4px 0 20px rgba(0,0,0,.3);
}}
@media (max-width: 400px) {{
  #stats-panel {{ width: 100vw; }}
}}
#stats-header {{
  background: var(--bg-header); color: var(--text-header);
  padding: 14px 16px;
  padding-top: max(14px, env(safe-area-inset-top, 14px));
  display: flex; align-items: center; gap: 10px;
  font-size: 15px; font-weight: 600; flex-shrink: 0;
}}
#stats-close {{
  margin-left: auto; background: none; border: none; cursor: pointer;
  color: var(--text-header); font-size: 24px; line-height: 1;
  padding: 4px 8px; min-width: 40px; min-height: 40px;
  display: flex; align-items: center; justify-content: center;
}}
#stats-summary {{
  padding: 10px 16px; font-size: 13px; color: var(--text-muted);
  border-bottom: 1px solid var(--border); flex-shrink: 0;
}}
#stats-list {{ padding: 8px 0; flex: 1; }}
.stat-row {{
  display: flex; align-items: center; gap: 10px;
  padding: 10px 16px; cursor: pointer; transition: background .1s;
  min-height: 56px;
}}
.stat-row:hover  {{ background: rgba(128,128,128,.08); }}
.stat-row.active {{ background: rgba(18,140,126,.12); }}
.stat-avatar {{
  width: 38px; height: 38px; border-radius: 50%; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; color: #fff; user-select: none;
}}
.stat-info {{ flex: 1; min-width: 0; }}
.stat-name {{
  font-size: 13px; font-weight: 600; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; color: var(--text-main);
}}
.stat-bar-wrap {{
  height: 4px; background: var(--stat-bar-bg); border-radius: 2px;
  margin-top: 5px; overflow: hidden;
}}
.stat-bar {{ height: 100%; border-radius: 2px; width: 0; }}
.stat-nums {{ text-align: right; flex-shrink: 0; }}
.stat-msg-count  {{ display: block; font-size: 14px; font-weight: 700; color: var(--text-main); }}
.stat-media-count{{ display: block; font-size: 11px; color: var(--text-muted); }}
</style>
</head>
<body>

<!-- ═══ Header ═══ -->
<div id="header">
  <div class="chat-avatar">{html.escape(initials(chat_name))}</div>
  <h1>{html.escape(chat_name)}</h1>
  <div class="header-actions">
    <span id="msg-count"></span>
    <button class="icon-btn" id="stats-btn" title="Sender stats" aria-label="Sender stats">&#x1F4CA;</button>
    <button class="icon-btn" id="dark-btn"  title="Toggle dark mode" aria-label="Toggle dark mode">&#x1F319;</button>
  </div>
</div>

<!-- ═══ Toolbar ═══ -->
<div id="toolbar">
  <div id="search-row">
    <input type="search" id="search-input" placeholder="Search…" autocomplete="off" aria-label="Search messages">
    <button id="filter-toggle" title="Show filters" aria-expanded="false">&#x1F50D;</button>
    <span id="match-count"></span>
  </div>
  <div id="toolbar-filters" class="collapsed">
    <select class="toolbar-select" id="sender-filter" aria-label="Filter by sender">
      {sender_options}
    </select>
    <input type="date" class="toolbar-date" id="date-picker"
           min="{date_min}" max="{date_max}" aria-label="Jump to date">
    <button id="jump-btn">Go</button>
  </div>
</div>

<!-- ═══ Chat (virtual scroll host) ═══ -->
<div id="chat" role="log" aria-live="off">
  <div id="spacer-top"></div>
  <div id="vlist"></div>
  <div id="spacer-bottom"></div>
</div>

<!-- ═══ Stats overlay ═══ -->
<div id="stats-overlay" role="dialog" aria-modal="true" aria-label="Sender stats">
  <div id="stats-panel">
    <div id="stats-header">
      &#x1F4CA; Sender Stats
      <button id="stats-close" aria-label="Close">&times;</button>
    </div>
    <div id="stats-summary"></div>
    <div id="stats-list">
{stats_rows_html}
    </div>
  </div>
</div>

<script>
(function () {{
  'use strict';

  /* ════════════════════════════════════════════════════════════════════════
     DATA
     ════════════════════════════════════════════════════════════════════════ */
  const ALL_ROWS   = {rows_json};
  const palette    = {palette_json};
  const totalMsgs  = {total_messages};

  /* ════════════════════════════════════════════════════════════════════════
     ELEMENTS
     ════════════════════════════════════════════════════════════════════════ */
  const chat         = document.getElementById('chat');
  const vlist        = document.getElementById('vlist');
  const spacerTop    = document.getElementById('spacer-top');
  const spacerBot    = document.getElementById('spacer-bottom');
  const searchInput  = document.getElementById('search-input');
  const matchCountEl = document.getElementById('match-count');
  const msgCountEl   = document.getElementById('msg-count');
  const senderSel    = document.getElementById('sender-filter');
  const datePicker   = document.getElementById('date-picker');
  const jumpBtn      = document.getElementById('jump-btn');
  const darkBtn      = document.getElementById('dark-btn');
  const statsBtn     = document.getElementById('stats-btn');
  const statsOverlay = document.getElementById('stats-overlay');
  const statsClose   = document.getElementById('stats-close');
  const statsSummary = document.getElementById('stats-summary');
  const filterToggle = document.getElementById('filter-toggle');
  const toolbarFilters = document.getElementById('toolbar-filters');

  msgCountEl.textContent = totalMsgs.toLocaleString() + ' msgs';

  /* ════════════════════════════════════════════════════════════════════════
     DARK MODE
     ════════════════════════════════════════════════════════════════════════ */
  function applyDark(on) {{
    document.body.classList.toggle('dark', on);
    darkBtn.textContent = on ? '☀️' : '🌙';
    try {{ localStorage.setItem('wa-dark', on ? '1' : '0'); }} catch(_) {{}}
  }}
  (function initDark() {{
    let saved;
    try {{ saved = localStorage.getItem('wa-dark'); }} catch(_) {{}}
    applyDark(saved !== null
      ? saved === '1'
      : window.matchMedia('(prefers-color-scheme: dark)').matches);
  }})();
  darkBtn.addEventListener('click', () =>
    applyDark(!document.body.classList.contains('dark')));

  /* ════════════════════════════════════════════════════════════════════════
     FILTER TOGGLE (mobile)
     ════════════════════════════════════════════════════════════════════════ */
  filterToggle.addEventListener('click', () => {{
    const collapsed = toolbarFilters.classList.toggle('collapsed');
    filterToggle.classList.toggle('active', !collapsed);
    filterToggle.setAttribute('aria-expanded', String(!collapsed));
  }});

  /* ════════════════════════════════════════════════════════════════════════
     STATS PANEL
     ════════════════════════════════════════════════════════════════════════ */
  (function initStatBars() {{
    const bars = Array.from(document.querySelectorAll('.stat-bar'));
    if (!bars.length) return;
    const maxCount = Math.max(...bars.map(b => parseInt(b.dataset.count || '0', 10)));
    bars.forEach(b => {{
      const pct = maxCount > 0 ? parseInt(b.dataset.count, 10) / maxCount * 100 : 0;
      b.style.width = pct + '%';
    }});
  }})();

  statsSummary.textContent =
    totalMsgs.toLocaleString() + ' messages · ' +
    Object.keys(palette).length + ' participants';

  statsBtn.addEventListener('click',  () => statsOverlay.classList.add('open'));
  statsClose.addEventListener('click',() => statsOverlay.classList.remove('open'));
  statsOverlay.addEventListener('click', e => {{
    if (e.target === statsOverlay) statsOverlay.classList.remove('open');
  }});

  document.querySelectorAll('.stat-row').forEach(row => {{
    row.addEventListener('click', () => {{
      senderSel.value = row.dataset.sender;
      statsOverlay.classList.remove('open');
      applyFilters();
    }});
  }});

  /* ════════════════════════════════════════════════════════════════════════
     FILTERING  — produces `filtered` index array
     ════════════════════════════════════════════════════════════════════════ */
  let filtered = ALL_ROWS.map((_, i) => i);   // indices into ALL_ROWS
  let activeQ  = '';
  let activeSender = '';

  function escapeRegex(s) {{
    return s.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
  }}

  function applyFilters() {{
    const q      = searchInput.value.trim().toLowerCase();
    const sender = senderSel.value;
    activeQ      = q;
    activeSender = sender;

    filtered = [];
    for (let i = 0; i < ALL_ROWS.length; i++) {{
      const r = ALL_ROWS[i];
      // Always keep date separators and system msgs (they'll be shown/hidden
      // contextually in the renderer, not filtered here)
      if (r.kind !== 'message') {{ filtered.push(i); continue; }}
      if (sender && r.sender !== sender) continue;
      if (q && !r.searchable.includes(q) && !r.sender.toLowerCase().includes(q)) continue;
      filtered.push(i);
    }}

    // Count only message-kind items
    let msgMatched = filtered.filter(i => ALL_ROWS[i].kind === 'message').length;

    if (q || sender) {{
      matchCountEl.textContent = msgMatched.toLocaleString() + ' results';
      msgCountEl.textContent   = msgMatched.toLocaleString() + ' / ' +
                                  totalMsgs.toLocaleString() + ' msgs';
    }} else {{
      matchCountEl.textContent = '';
      msgCountEl.textContent   = totalMsgs.toLocaleString() + ' msgs';
    }}

    document.querySelectorAll('.stat-row').forEach(r => {{
      r.classList.toggle('active', r.dataset.sender === sender && sender !== '');
    }});

    // Reset virtual scroll to top
    renderWindow(0, true);
  }}

  searchInput.addEventListener('input', applyFilters);
  senderSel.addEventListener('change', applyFilters);

  /* ════════════════════════════════════════════════════════════════════════
     VIRTUAL SCROLL
     ════════════════════════════════════════════════════════════════════════ */
  const PAGE      = 80;    // items rendered at once
  const OVERSCAN  = 20;    // extra items beyond visible edge
  const AVG_H     = 72;    // estimated average row height (px) for spacer calc

  let winStart = 0;        // first rendered index in `filtered`
  let winEnd   = 0;        // last rendered index  in `filtered` (exclusive)

  function highlight(text, q) {{
    if (!q) return text;
    const re = new RegExp('(' + escapeRegex(q) + ')', 'gi');
    return text.replace(re, '<mark>$1</mark>');
  }}

  function rowHTML(rowIdx) {{
    const r = ALL_ROWS[filtered[rowIdx]];

    if (r.kind === 'date') {{
      return `<div class="date-sep" data-date="${{r.date}}"><span>${{r.label}}</span></div>`;
    }}
    if (r.kind === 'system') {{
      return `<div class="sys-msg">${{r.text}}</div>`;
    }}

    // message
    const q   = activeQ;
    const txt = q ? highlight(r.text_html, q) : r.text_html;
    const namePart = r.show_name
      ? `<div class="sender-name" style="color:${{r.color}}">${{r.sender}}</div>`
      : '';
    const mediaPart = r.media_html
      ? `<div class="media-wrap">${{r.media_html}}</div>` : '';
    const textPart  = txt
      ? `<div class="msg-text">${{txt}}</div>` : '';

    return (
      `<div class="msg-row" data-idx="${{rowIdx}}">` +
        `<div class="avatar" style="background:${{r.color}}" title="${{r.sender}}">${{r.inits}}</div>` +
        `<div class="bubble">` +
          namePart + mediaPart + textPart +
          `<div class="msg-time">${{r.time}}</div>` +
        `</div>` +
      `</div>`
    );
  }}

  function renderWindow(startIdx, resetScroll) {{
    const total = filtered.length;
    const start = Math.max(0, startIdx - OVERSCAN);
    const end   = Math.min(total, startIdx + PAGE + OVERSCAN);

    winStart = start;
    winEnd   = end;

    const html_parts = [];
    for (let i = start; i < end; i++) {{
      html_parts.push(rowHTML(i));
    }}
    vlist.innerHTML = html_parts.join('');

    // Spacers compensate for unrendered items
    spacerTop.style.height = (start * AVG_H) + 'px';
    spacerBot.style.height = ((total - end) * AVG_H) + 'px';

    if (resetScroll) {{
      // Scroll to bottom when showing all messages, to top when filtering
      if (!activeQ && !activeSender) {{
        chat.scrollTop = chat.scrollHeight;
      }} else {{
        chat.scrollTop = 0;
      }}
    }}
  }}

  // Initial render — scroll to bottom
  renderWindow(Math.max(0, filtered.length - PAGE), false);
  chat.scrollTop = chat.scrollHeight;

  // Scroll handler — slide the window as user scrolls
  let scrollRaf = null;
  chat.addEventListener('scroll', () => {{
    if (scrollRaf) return;
    scrollRaf = requestAnimationFrame(() => {{
      scrollRaf = null;
      const scrollTop  = chat.scrollTop;
      const clientH    = chat.clientHeight;
      const scrollH    = chat.scrollHeight;
      const total      = filtered.length;

      // Estimate which row index is at top of viewport
      const topSpacerH = parseFloat(spacerTop.style.height) || 0;
      const relScroll  = scrollTop - topSpacerH;
      const estIdx     = winStart + Math.max(0, Math.floor(relScroll / AVG_H));

      // Slide window if we're within OVERSCAN rows of either edge
      const nearTop = estIdx < winStart + OVERSCAN;
      const nearBot = estIdx > winEnd   - OVERSCAN;

      if (nearTop && winStart > 0) {{
        renderWindow(Math.max(0, estIdx - PAGE / 2), false);
      }} else if (nearBot && winEnd < total) {{
        renderWindow(Math.min(total - PAGE, estIdx), false);
      }}
    }});
  }}, {{ passive: true }});

  /* ════════════════════════════════════════════════════════════════════════
     JUMP TO DATE
     ════════════════════════════════════════════════════════════════════════ */
  function jumpToDate(isoDate) {{
    if (!isoDate) return;
    // Find first date-sep row in filtered on or after isoDate
    let targetIdx = -1;
    for (let i = 0; i < filtered.length; i++) {{
      const r = ALL_ROWS[filtered[i]];
      if (r.kind === 'date' && r.date >= isoDate) {{ targetIdx = i; break; }}
    }}
    if (targetIdx === -1 && filtered.length > 0) targetIdx = filtered.length - 1;
    if (targetIdx === -1) return;

    renderWindow(targetIdx, false);
    // After render, find the date-sep element and scroll to it
    requestAnimationFrame(() => {{
      const el = vlist.querySelector('.date-sep');
      if (el) el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      else chat.scrollTop = parseFloat(spacerTop.style.height) || 0;
    }});
  }}

  jumpBtn.addEventListener('click', () => jumpToDate(datePicker.value));
  datePicker.addEventListener('keydown', e => {{
    if (e.key === 'Enter') jumpToDate(datePicker.value);
  }});

  /* ════════════════════════════════════════════════════════════════════════
     KEYBOARD SHORTCUTS
     ════════════════════════════════════════════════════════════════════════ */
  document.addEventListener('keydown', e => {{
    const tag = document.activeElement.tagName;
    const inInput = tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA';
    if (e.key === '/' && !inInput) {{
      e.preventDefault();
      searchInput.focus();
    }}
    if (e.key === 'Escape') {{
      if (statsOverlay.classList.contains('open')) {{
        statsOverlay.classList.remove('open');
      }} else if (!toolbarFilters.classList.contains('collapsed')) {{
        toolbarFilters.classList.add('collapsed');
        filterToggle.classList.remove('active');
      }} else {{
        searchInput.value = '';
        senderSel.value   = '';
        applyFilters();
        searchInput.blur();
      }}
    }}
  }});
}})();
</script>
</body>
</html>
"""


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
