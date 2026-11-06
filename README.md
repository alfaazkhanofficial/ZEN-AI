# Zen

ChatGPT-style desktop app. Electron + React/TS/Vite UI, Python (FastAPI) backend.
V1: Nemotron 3 (NVIDIA endpoint, preconfigured), vector memory, Tavily web search (auto per query), time/context awareness, Light/Dark/System themes. Everything configurable in Settings.

## v1.1 features
- **Link reading** - paste any URL (page, PDF, doc) and Zen fetches and reads it; the content stays in the chat context.
- **File upload** - drag/drop, paste or `+`. Extracts PDF, DOCX, XLSX, PPTX, ZIP, HTML, CSV/JSON/code and any text. Big files are chunked into the vector store and searched per question. Images go to vision-capable models (tick *Vision* on a model in Settings → Models).
- **File creation** - ask for a `.docx/.xlsx/.pptx/.pdf` or any text/code file (`.csv .json .html .py .svg ...`); it appears as a card with Open / Save.
- **Image generation** - Pollinations AI (`gen.pollinations.ai`, legacy fallback built in). Ask in chat, or `+` → Create image. Optional API key in Settings → Tools & files.
- **Chat power-ups** - edit & resend, regenerate, stop, export chat to Markdown, syntax-highlighted code, scroll-to-bottom, suggestion chips, shortcuts: `Ctrl+Shift+O` new chat, `Ctrl+B` sidebar, `Ctrl+,` settings, `Esc` stop.
- Motion pass: spring modals/menus, staged message entry, blur-up images, shimmer status, reduced-motion respected.

## Run (dev)
```
pip install -r backend/requirements.txt
npm install
npm run dev
```
Open Settings (bottom-left) → Models → paste your NVIDIA key (`nvapi-…`), Web search → paste Tavily key (`tvly-…`). Env vars `NVIDIA_API_KEY` / `TAVILY_API_KEY` also work. Data lives in the Electron userData folder (`zen.db`).

Use a virtualenv for Python (`python -m venv .venv`, activate it, then `pip install -r backend/requirements.txt`).

## Release
```
python scripts/freeze_backend.py     # PyInstaller → backend_dist/zen-backend/
python scripts/build_installer.py    # freeze (if needed) + vite build + electron-builder → release/
```
Build on the OS you ship for (Windows → NSIS .exe, macOS → .dmg, Linux → AppImage). Add `build/icon.ico|icns|png` for a custom icon.

## Notes
- Model default is `nvidia/nemotron-3-nano-30b-a3b` labelled "Nemotron 3 Lightning". If your "lightning" model has a different id, change it in Settings → Models.
- Memory embeddings default to `nvidia/nv-embedqa-e5-v5` on the same NVIDIA key; if unreachable, an offline hashed fallback is used so memory still works.
- Settings → Memory & context lists/edits saved memories.
- Not supported: OCR of scanned PDFs/images for text-only models; generating binary formats other than docx/xlsx/pptx/pdf (use SVG for graphics).
- The frozen backend is ~260 MB (office/PDF libraries); expect a ~100-150 MB installer.
