# WhatsApp Local Viewer

Browse any WhatsApp exported chat in your browser — with a WhatsApp-like UI, full media support, virtual scroll, dark mode, search, and more.

Two ways to use it:

| | `index.html` — Standalone | `whatsapp_viewer.py` — Python |
|---|---|---|
| Requires Python | No | Yes (3.10+) |
| Requires internet | Yes (loads `viewer.js`) | Yes (loads `viewer.js`) |
| Re-run on new backup | No — just open & pick zip | Yes — regenerate HTML |
| Media access | Read directly from zip | Relative paths on disk |

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![No dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)

---

## Features

- **WhatsApp-like UI** — colour-coded sender bubbles, avatar initials, timestamps, date separators
- **All media types** — images, video with poster frame preview, audio player, documents, contacts
- **Group & 1-on-1** chats — auto-detected, senders colour-coded
- **Virtual scroll** — only ~80 rows in the DOM at once; handles chats of any size smoothly
- **Dark mode** — toggle with `🌙`, preference saved in `localStorage`, respects system setting
- **Live search** — keyword filter with match highlighting (press `/` to focus)
- **Sender filter** — dropdown to show messages from one participant; combines with search
- **Jump to date** — date picker scrolls to the nearest date in the chat
- **Stats panel** — per-sender message and media counts with proportional bars
- **Auto-detects** iOS and Android export formats
- **System messages** — join/leave/admin events shown in muted centre style
- **RTL support** — Hebrew, Arabic and other RTL text rendered correctly
- **WhatsApp markdown** — `*bold*`, `_italic_`, `~strike~`, ` ```mono``` `
- **Mobile-friendly** — safe-area insets, touch targets, collapsible filter toolbar

---

## Option 1 — Standalone `index.html` (no Python needed)

1. Download `index.html` from this repo and put it anywhere
2. Open it in Chrome or Firefox
3. Drag your WhatsApp export `.zip` onto the page, or click to browse
4. The chat renders directly in the browser — the zip is parsed entirely client-side

> `index.html` fetches `viewer.js` from this repo on load so it always uses the latest version.

---

## Option 2 — Python script

### Requirements

- Python 3.10 or newer
- No third-party packages

### 1. Export your chat from WhatsApp

**iOS:** Open chat → tap name → scroll down → **Export Chat** → **Attach Media** → save the `.zip`

**Android:** Open chat → ⋮ menu → **More** → **Export Chat** → **Include Media** → save the `.zip`

### 2. Run the script

```bash
python3 whatsapp_viewer.py "WhatsApp Chat - My Group.zip"
```

The script and the zip can be in different folders — output is always written next to the zip:

```bash
python3 ~/tools/whatsapp_viewer.py ~/Downloads/"WhatsApp Chat - Family.zip"
```

> **Tip:** On macOS you can drag the zip into the terminal after typing the command to auto-fill its path.

### 3. Open the HTML

```
📂 same folder as the zip
├── WhatsApp Chat - My Group.zip       ← original, unchanged
├── WhatsApp Chat - My Group.html      ← open this in your browser
└── WhatsApp Chat - My Group/          ← extracted media (keep alongside the HTML)
    ├── _chat.txt
    ├── 00000001-PHOTO-....jpg
    ├── 00000002-VIDEO-....mp4
    └── ...
```

The HTML references media via **relative paths** — keep the extracted folder alongside the HTML file.

Re-running is fast: already-extracted files are skipped.

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus search bar |
| `Esc` | Clear search / close panels |

---

## Supported export formats

| Platform | Example line |
|----------|-------------|
| iOS | `[03/09/2023, 11:58:39] Alice: Hello!` |
| Android | `03/09/2023, 11:58 - Alice: Hello!` |

---

## How it works

```
viewer.js          — rendering engine (virtual scroll, UI, dark mode, search)
index.html         — standalone loader: parses zip in-browser via fetch()+eval
whatsapp_viewer.py — Python script: extracts zip, parses chat, emits HTML shell
                     The HTML shell fetches viewer.js at open time from this repo
```

`viewer.js` is fetched fresh each time a chat is opened, so improvements to the viewer are picked up automatically without regenerating the HTML or re-running the script.

---

## Privacy

- `index.html` — your zip file never leaves the browser tab; all parsing is done in JavaScript locally
- Python mode — the script reads and writes only local files
- `viewer.js` is the only network request made at open time (fetched from GitHub)
- No analytics, no telemetry, no tracking of any kind

---

## License

MIT — see [LICENSE](LICENSE).
