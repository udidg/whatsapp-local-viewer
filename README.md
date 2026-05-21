# WhatsApp Local Viewer

Convert a WhatsApp exported `.zip` file into a self-contained, browsable HTML file — entirely offline, no data ever leaves your machine.

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![No dependencies](https://img.shields.io/badge/dependencies-none-brightgreen)

---

## Features

- **100% local** — pure Python stdlib, zero external packages, zero network calls
- **Auto-detects** iOS and Android export formats
- **WhatsApp-like UI** — colour-coded sender bubbles, avatar initials, timestamps, date separators
- **All media types** — images (inline), video (`<video>`), audio (`<audio>`), documents and contacts (download links)
- **Group & 1-on-1** chats — auto-detected, senders colour-coded
- **System messages** — join/leave/admin events shown in muted centre style
- **Live search** — client-side keyword filter with match highlighting (press `/` to focus, `Esc` to clear)
- **Incremental extraction** — re-running skips already-extracted files

---

## Requirements

- Python 3.10 or newer
- No third-party packages

---

## Usage

### 1. Export your chat from WhatsApp

**iOS:** Open chat → tap name → Scroll down → **Export Chat** → **Attach Media** → save the `.zip`

**Android:** Open chat → ⋮ menu → **More** → **Export Chat** → **Include Media** → save the `.zip`

### 2. Run the script

```bash
python whatsapp_viewer.py "WhatsApp Chat - My Group.zip"
```

Place `whatsapp_viewer.py` anywhere — it will write the output next to the zip file.

### 3. Open the HTML

```
WhatsApp Chat - My Group.html   ← open this in your browser
WhatsApp Chat - My Group/       ← extracted media (keep alongside the HTML)
```

---

## Output structure

```
📂 same folder as the zip
├── WhatsApp Chat - My Group.zip       (original, unchanged)
├── WhatsApp Chat - My Group.html      (generated viewer)
└── WhatsApp Chat - My Group/          (extracted by the script)
    ├── _chat.txt
    ├── 00000001-PHOTO-....jpg
    ├── 00000002-VIDEO-....mp4
    └── ...
```

The HTML file references media via **relative paths**, so keep the extracted folder alongside the HTML. Moving just the HTML will break media links.

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `/` | Focus search bar |
| `Esc` | Clear search |

---

## Supported formats

| Format | Example line |
|--------|-------------|
| iOS | `[03/09/2023, 11:58:39] Alice: Hello!` |
| Android | `03/09/2023, 11:58 - Alice: Hello!` |

Multi-line messages, emoji in names, RTL text (Hebrew, Arabic), and WhatsApp markdown (`*bold*`, `_italic_`, `~strike~`, ` ```mono``` `) are all handled.

---

## Privacy

Your chat data never leaves your computer. The script reads the zip, writes local files, and generates a local HTML file. There are no analytics, no telemetry, and no network requests of any kind.

---

## License

MIT — see [LICENSE](LICENSE).
