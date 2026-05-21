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
    # Pre-assign colours
    for msg in messages:
        if msg["type"] == "message" and msg["sender"]:
            sender_color(msg["sender"], color_palette)

    # Serialise palette for JS
    palette_json = json.dumps(color_palette)

    # ── Bubble rows ──────────────────────────────────────────────────────────
    rows_html_parts: list[str] = []
    prev_date: str | None = None
    prev_sender: str | None = None

    for msg in messages:
        dt: datetime | None = msg.get("date")
        date_label = dt.strftime("%-d %B %Y") if dt else ""
        time_label = dt.strftime("%H:%M") if dt else ""

        # Date separator
        if date_label and date_label != prev_date:
            rows_html_parts.append(
                f'<div class="date-sep"><span>{html.escape(date_label)}</span></div>'
            )
            prev_date = date_label
            prev_sender = None

        if msg["type"] == "system":
            sys_text = html.escape(msg["text"].strip())
            if sys_text:
                rows_html_parts.append(
                    f'<div class="sys-msg" data-searchable="{sys_text.lower()}">'
                    f'{sys_text}</div>'
                )
            continue

        # Regular message
        sender   = msg["sender"]
        color    = color_palette.get(sender, "#555")
        inits    = initials(sender)
        text_h   = text_to_html(msg["text"])
        media_h  = ""
        if msg.get("media") and msg["media"] in available_media:
            media_h = media_html(msg["media"], media_dir_rel)

        # Show sender name only when it changes (group-chat style)
        show_name = (sender != prev_sender)
        prev_sender = sender

        sender_esc = html.escape(sender)
        searchable = html.escape((msg.get("text") or "").lower())

        avatar_html = (
            f'<div class="avatar" style="background:{color}" title="{sender_esc}">'
            f'{html.escape(inits)}</div>'
        )

        name_html = (
            f'<div class="sender-name" style="color:{color}">{sender_esc}</div>'
            if show_name else ""
        )

        bubble_content = ""
        if media_h:
            bubble_content += f'<div class="media-wrap">{media_h}</div>'
        if text_h:
            bubble_content += f'<div class="msg-text">{text_h}</div>'
        bubble_content += f'<div class="msg-time">{html.escape(time_label)}</div>'

        rows_html_parts.append(
            f'<div class="msg-row" data-sender="{sender_esc}" '
            f'data-searchable="{searchable}">'
            f'{avatar_html}'
            f'<div class="bubble">'
            f'{name_html}'
            f'{bubble_content}'
            f'</div>'
            f'</div>'
        )

    rows_html = "\n".join(rows_html_parts)

    return f"""<!DOCTYPE html>
<html lang="he" dir="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(chat_name)}</title>
<style>
/* ── Reset & Base ── */
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
html, body {{ height: 100%; font-family: -apple-system, BlinkMacSystemFont,
    'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 14px; }}
body {{ display: flex; flex-direction: column;
    background: #ECE5DD; color: #111; overflow: hidden; }}

/* ── Header ── */
#header {{
    display: flex; align-items: center; gap: 12px;
    background: #128C7E; color: #fff;
    padding: 10px 16px; flex-shrink: 0; box-shadow: 0 1px 3px rgba(0,0,0,.3);
}}
#header .chat-avatar {{
    width: 40px; height: 40px; border-radius: 50%;
    background: #25D366; display: flex; align-items: center;
    justify-content: center; font-weight: 700; font-size: 16px; color: #fff;
    flex-shrink: 0;
}}
#header h1 {{ font-size: 16px; font-weight: 600; flex: 1; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }}
#header .msg-count {{ font-size: 12px; opacity: .8; }}

/* ── Search bar ── */
#search-bar {{
    display: flex; align-items: center; gap: 8px;
    background: #f0f0f0; padding: 6px 12px; flex-shrink: 0;
    border-bottom: 1px solid #ccc;
}}
#search-bar input {{
    flex: 1; border: 1px solid #ccc; border-radius: 20px;
    padding: 6px 14px; font-size: 13px; outline: none;
    background: #fff;
}}
#search-bar input:focus {{ border-color: #128C7E; }}
#search-bar .match-count {{ font-size: 12px; color: #555; min-width: 80px; text-align: right; }}

/* ── Chat window ── */
#chat {{
    flex: 1; overflow-y: auto; padding: 12px 16px;
    display: flex; flex-direction: column; gap: 2px;
}}

/* ── Date separator ── */
.date-sep {{
    display: flex; align-items: center; justify-content: center;
    margin: 10px 0;
}}
.date-sep span {{
    background: #D9F7BE; color: #555; font-size: 12px;
    padding: 3px 10px; border-radius: 8px;
    box-shadow: 0 1px 2px rgba(0,0,0,.15);
}}

/* ── System message ── */
.sys-msg {{
    text-align: center; font-size: 12px; color: #555;
    background: rgba(255,255,255,.7); border-radius: 8px;
    padding: 3px 10px; margin: 4px auto;
    max-width: 80%;
}}

/* ── Message row ── */
.msg-row {{
    display: flex; align-items: flex-end; gap: 6px;
    max-width: 75%; align-self: flex-start;
    margin-bottom: 2px;
}}
.msg-row.hidden {{ display: none; }}

/* ── Avatar ── */
.avatar {{
    width: 32px; height: 32px; border-radius: 50%;
    flex-shrink: 0; display: flex; align-items: center;
    justify-content: center; font-size: 12px; font-weight: 700;
    color: #fff;
}}

/* ── Bubble ── */
.bubble {{
    background: #fff; border-radius: 8px 8px 8px 0;
    padding: 6px 8px 4px; box-shadow: 0 1px 1px rgba(0,0,0,.13);
    max-width: 100%; min-width: 80px;
    position: relative; word-break: break-word;
}}

/* ── Sender name inside bubble ── */
.sender-name {{
    font-size: 12px; font-weight: 700; margin-bottom: 2px;
}}

/* ── Message text ── */
.msg-text {{ font-size: 14px; line-height: 1.45; white-space: pre-wrap; }}

/* ── Timestamp ── */
.msg-time {{
    font-size: 11px; color: #999; text-align: right;
    margin-top: 2px;
}}

/* ── Media ── */
.media-wrap {{ margin-bottom: 4px; }}
.media-img {{
    max-width: 280px; max-height: 280px; border-radius: 6px;
    display: block; cursor: pointer; object-fit: contain;
}}
.media-video {{
    max-width: 280px; border-radius: 6px; display: block;
}}
.media-audio {{
    max-width: 260px; display: block;
}}
.media-doc {{
    display: inline-flex; align-items: center; gap: 6px;
    background: #f5f5f5; border-radius: 8px;
    padding: 8px 12px; text-decoration: none; color: #333;
    font-size: 13px; border: 1px solid #ddd;
}}
.media-doc:hover {{ background: #e8e8e8; }}

/* ── Highlighted search match ── */
mark {{ background: #FFD700; border-radius: 2px; padding: 0 1px; }}

/* ── Scrollbar ── */
#chat::-webkit-scrollbar {{ width: 6px; }}
#chat::-webkit-scrollbar-thumb {{ background: #bbb; border-radius: 3px; }}
</style>
</head>
<body>

<div id="header">
  <div class="chat-avatar">{html.escape(initials(chat_name))}</div>
  <h1>{html.escape(chat_name)}</h1>
  <div class="msg-count" id="msg-count"></div>
</div>

<div id="search-bar">
  <input type="search" id="search-input" placeholder="Search messages…" autocomplete="off">
  <div class="match-count" id="match-count"></div>
</div>

<div id="chat">
{rows_html}
</div>

<script>
(function () {{
  const palette = {palette_json};
  const rows    = Array.from(document.querySelectorAll('.msg-row'));
  const sysRows = Array.from(document.querySelectorAll('.sys-msg'));
  const input   = document.getElementById('search-input');
  const countEl = document.getElementById('match-count');
  const msgCountEl = document.getElementById('msg-count');

  msgCountEl.textContent = rows.length + ' messages';

  // Scroll to bottom on load
  const chat = document.getElementById('chat');
  chat.scrollTop = chat.scrollHeight;

  function escapeRegex(s) {{
    return s.replace(/[.*+?^${{}}()|[\\]\\\\]/g, '\\\\$&');
  }}

  function highlightNode(node, re) {{
    if (node.nodeType === Node.TEXT_NODE) {{
      const text = node.textContent;
      const m = re.exec(text);
      if (!m) return null;
      const frag = document.createDocumentFragment();
      frag.appendChild(document.createTextNode(text.slice(0, m.index)));
      const mark = document.createElement('mark');
      mark.textContent = m[0];
      frag.appendChild(mark);
      frag.appendChild(document.createTextNode(text.slice(m.index + m[0].length)));
      return frag;
    }}
    return null;
  }}

  function clearHighlights(el) {{
    el.querySelectorAll('mark').forEach(m => {{
      const parent = m.parentNode;
      parent.replaceChild(document.createTextNode(m.textContent), m);
      parent.normalize();
    }});
  }}

  function applyHighlights(el, re) {{
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const replacements = [];
    let node;
    while ((node = walker.nextNode())) {{
      const frag = highlightNode(node, re);
      if (frag) replacements.push([node, frag]);
    }}
    for (const [node, frag] of replacements) {{
      node.parentNode.replaceChild(frag, node);
    }}
  }}

  let lastQuery = '';

  input.addEventListener('input', function () {{
    const q = this.value.trim().toLowerCase();
    if (q === lastQuery) return;
    lastQuery = q;

    // Clear all highlights first
    rows.forEach(r => {{ clearHighlights(r); r.classList.remove('hidden'); }});
    sysRows.forEach(r => {{ clearHighlights(r); r.classList.remove('hidden'); }});
    document.querySelectorAll('.date-sep').forEach(d => d.classList.remove('hidden'));

    if (!q) {{
      countEl.textContent = '';
      msgCountEl.textContent = rows.length + ' messages';
      return;
    }}

    const re = new RegExp(escapeRegex(q), 'gi');
    let matched = 0;

    rows.forEach(r => {{
      const searchable = (r.dataset.searchable || '').toLowerCase();
      const senderText = (r.dataset.sender || '').toLowerCase();
      if (searchable.includes(q) || senderText.includes(q)) {{
        matched++;
        applyHighlights(r, re);
      }} else {{
        r.classList.add('hidden');
      }}
    }});

    countEl.textContent = matched === 0 ? 'No results' : matched + ' results';
    msgCountEl.textContent = matched + ' / ' + rows.length + ' messages';
  }});

  // Keyboard shortcut: / to focus search
  document.addEventListener('keydown', function (e) {{
    if (e.key === '/' && document.activeElement !== input) {{
      e.preventDefault();
      input.focus();
    }}
    if (e.key === 'Escape') {{
      input.value = '';
      input.dispatchEvent(new Event('input'));
      input.blur();
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
