# Zen — V1 spec (source of truth)
**Goal:** ChatGPT-identical desktop app named Zen. Stack: Electron, Python (FastAPI), TypeScript, Vite, React.
**Models:** single model Nemotron 3 (NVIDIA OpenAI-compatible endpoint, preconfigured). Models/endpoints/keys editable in Settings.
**Features:** exact ChatGPT UI (sidebar w/ grouped history, search, rename/delete, model picker, pill composer, streaming markdown, code copy, sources chips); vector memory (auto-extract + recall, embeddings endpoint configurable, offline fallback); context awareness (history trimmed to a char budget; client date/time/timezone in system prompt); Tavily internet access routed automatically by an LLM decision per query (auto/always/off); time-of-day personalisation (greeting + prompt).
**Themes:** Light, Dark, System only.
**Architecture decisions:** one-file backend (`backend/server.py`, SQLite), Electron picks a free port and spawns backend; plain-JS Electron main (CJS) to avoid a compile step; renderer in TS.
**Release:** `scripts/freeze_backend.py` (PyInstaller onedir) and `scripts/build_installer.py` (freeze → vite build → electron-builder).
**V1.1 additions:** link reading (httpx + HTML→text, PDFs/docs via extractors); uploads (raw-body POST, extractors for pdf/docx/xlsx/pptx/zip/html/text, RAG chunking >16k chars); file creation via `<zen-file name>` tags parsed from the stream (docx/xlsx/pptx/pdf builders, raw text otherwise); images via `<zen-image>` tags or image mode → Pollinations; edit/regenerate/export; CSS-only motion system.
**Out of scope:** voice, OCR, multiple providers at once.
