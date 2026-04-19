# SignalVault Clipper

Chrome/Edge/Brave extension for one-click capture of articles and posts into your local SignalVault.

## Install (developer mode)

1. Start SignalVault locally: `python main.py web --port 5001`
2. Open `chrome://extensions`
3. Toggle **Developer mode** (top right)
4. Click **Load unpacked** and select this `extension/` directory
5. Pin the extension to the toolbar (puzzle icon → pin)

## Use

- **Toolbar button** — click the pin icon to open the capture popup
- **Right-click menu** — "Capture selection to SignalVault" or "Capture page to SignalVault"
- **Keyboard shortcut** — set your own at `chrome://extensions/shortcuts` (find "SignalVault Clipper" → "Open SignalVault capture popup" → click the edit icon and bind any key combo you like). No default is set so nothing conflicts with site "Save" hotkeys.

The popup pre-fills:
- Page title (editable)
- URL (display only)
- Source auto-detected from the domain (LinkedIn/X/Reddit/HN/News)
- Notes field with your highlighted text OR the page's `og:description`
- Author + published date from article meta tags when available

Click **Capture to SignalVault** (or press `Ctrl+Enter`) to save.

## Custom endpoint

If SignalVault runs on a different port, click ⚙ Settings in the popup and set the full endpoint URL, e.g. `http://localhost:5050/api/signals/manual`.

## Troubleshooting

- **"Could not reach SignalVault"** — confirm the server is running and the port matches. The extension only talks to `localhost:5001` by default.
- **CORS errors** — the server must allow the extension's origin. Flask-CORS is enabled for `/api/signals/manual` automatically.
