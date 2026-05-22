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


VIEWER_JS_RAW_URL = (
    "https://raw.githubusercontent.com/udidg/whatsapp-local-viewer/main/viewer.js"
)


def build_html(
    messages: list[dict],
    chat_name: str,
    media_dir_rel: str,
    available_media: set[str],
) -> str:
    """
    Build a self-contained HTML file:
    - embeds all message data as a JSON blob
    - fetches viewer.js from raw GitHub via fetch()+eval (auto-updates)
    - calls WA.init() once ready
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

    return (
        "<!DOCTYPE html>\n"
        '<html lang="he" dir="auto">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"<title>{html.escape(chat_name)}</title>\n"
        "</head>\n"
        "<body>\n"
        "<script>\n"
        "/* Embedded chat data — generated by whatsapp_viewer.py */\n"
        "window.__WA_CONFIG__ = {\n"
        f"  rows:      {rows_json},\n"
        f"  palette:   {palette_json},\n"
        f"  totalMsgs: {total_messages},\n"
        f"  chatName:  {json.dumps(chat_name)},\n"
        f"  mediaBase: {json.dumps(media_dir_rel)},\n"
        "  getMediaUrl: null\n"
        "};\n"
        f"fetch('{VIEWER_JS_RAW_URL}')\n"
        "  .then(function(r) {{\n"
        "    if (!r.ok) throw new Error('HTTP ' + r.status);\n"
        "    return r.text();\n"
        "  }})\n"
        "  .then(function(code) {{\n"
        "    (0, eval)(code);\n"
        "    WA.init(window.__WA_CONFIG__);\n"
        "  }})\n"
        "  .catch(function(e) {{\n"
        "    document.body.innerHTML = '<p style=\"padding:2rem;font-family:sans-serif;color:red\">'  \n"
        "      + 'Failed to load viewer.js: ' + e.message\n"
        "      + '<br>Check your internet connection and refresh.</p>';\n"
        "  }});\n"
        "</script>\n"
        "</body>\n"
        "</html>\n"
    )


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
