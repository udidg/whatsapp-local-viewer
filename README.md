# WhatsApp Local Viewer

Convert a WhatsApp exported `.zip` file into a self-contained, browsable HTML file — with a WhatsApp-like UI, full media support, dark mode, search, and more.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![No dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)

---

## Features

- **WhatsApp-like UI** — colour-coded sender bubbles, avatar initials, timestamps, date separators
- **All media types** — images inline, video with poster frame preview, audio player, documents and contacts as download links
- **Group & 1-on-1 chats** — auto-detected, senders colour-coded
- **Virtual scroll** — only ~80 rows in the DOM at once; handles chats of any size smoothly
- **Dark mode** — toggle with `🌙`, preference saved in `localStorage`, respects system setting
- **Live search** — keyword filter with match highlighting (press `/` to focus, `Esc` to clear)
- **Sender filter** — dropdown to show messages from one participant; combines with search
- **Jump to date** — date picker scrolls to the nearest date in the chat
- **Stats panel** — per-sender message and media counts with proportional bars
- **Auto-detects** iOS and Android export formats
- **System messages** — join/leave/admin events shown in muted centre style
- **RTL support** — Hebrew, Arabic and other RTL text rendered correctly
- **WhatsApp markdown** — `*bold*`, `_italic_`, `~strike~`, ` ```mono``` `
- **Mobile-friendly** — safe-area insets, touch targets, collapsible filter toolbar
- **100% self-contained** — the generated HTML embeds everything; no internet required to view it

---

## Requirements

- Python 3.10 or newer
- No third-party packages

---

## Usage

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

> **Tip:** On macOS, drag the zip file into the terminal after typing the command to auto-fill its path.

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

The HTML references media via **relative paths** — keep the extracted folder alongside the HTML. Re-running is fast: already-extracted files are skipped.

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

Multi-line messages, emoji in names, RTL text, and WhatsApp markdown are all handled.

---

## Privacy

Your chat data never leaves your computer. The script reads the zip, writes local files, and generates a local HTML file. There are no analytics, no telemetry, and no network requests of any kind.

---

## License

MIT — see [LICENSE](LICENSE).
