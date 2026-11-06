#!/usr/bin/env python3
"""Zen backend: chat streaming, vector memory, Tavily search, link reading, file upload/extraction,
file creation (docx/xlsx/pptx/pdf/text), Pollinations images, settings, history.
Single file. Run:  python backend/server.py --port 8765 --data-dir ~/.zen
"""
import argparse, asyncio, base64, csv, hashlib, io, json, math, mimetypes, os, random, re, sqlite3, threading, time, uuid, zipfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlparse
from xml.sax.saxutils import escape as xml_escape

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

# ───────────────────────── settings ─────────────────────────
DEFAULTS = {
    "theme": "system",
    "profile": {"name": "", "about": "", "instructions": ""},
    "chat": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key": "",  # falls back to env NVIDIA_API_KEY
        "model": "nvidia/nemotron-3-nano-30b-a3b",
        "models": [{"id": "nvidia/nemotron-3-nano-30b-a3b", "label": "Nemotron 3 Lightning", "vision": False}],
        "temperature": 0.6,
        "max_tokens": 4096,
        "thinking": False,
    },
    "embeddings": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "api_key": "",  # falls back to chat key, then env NVIDIA_API_KEY
        "model": "nvidia/nv-embedqa-e5-v5",
    },
    "memory": {"enabled": True, "top_k": 5, "min_score": 0.28},
    "search": {
        "mode": "auto",  # auto | always | off
        "base_url": "https://api.tavily.com",
        "api_key": "",  # falls back to env TAVILY_API_KEY
        "max_results": 5,
    },
    "context": {"max_chars": 24000},
    "image": {
        "base_url": "https://gen.pollinations.ai/image",
        "fallback_url": "https://image.pollinations.ai/prompt",
        "api_key": "",  # optional (enter.pollinations.ai); falls back to env POLLINATIONS_API_KEY
        "model": "flux",
        "width": 1024,
        "height": 1024,
        "enhance": True,
    },
    "tools": {"read_links": True, "create_files": True, "create_images": True},
}
DATA = Path.home() / ".zen"
RAG_THRESHOLD = 16000  # attachments longer than this are chunked into the vector store

DB = None
LOCK = threading.RLock()
TASKS = set()


def deep_merge(base, over):
    out = json.loads(json.dumps(base))
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def db_init(path: Path):
    global DB
    DB = sqlite3.connect(str(path), check_same_thread=False)
    DB.row_factory = sqlite3.Row
    DB.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, title TEXT, created REAL, updated REAL);
        CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, cid TEXT, role TEXT, content TEXT, sources TEXT, created REAL);
        CREATE INDEX IF NOT EXISTS idx_msg ON messages(cid, created);
        CREATE TABLE IF NOT EXISTS memories(id TEXT PRIMARY KEY, text TEXT, emb TEXT, emb_model TEXT, created REAL);
        CREATE TABLE IF NOT EXISTS uploads(id TEXT PRIMARY KEY, name TEXT, size INTEGER, kind TEXT, mime TEXT, chars INTEGER, rag INTEGER, created REAL);
        CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY, fid TEXT, idx INTEGER, text TEXT, emb TEXT, emb_model TEXT);
        CREATE INDEX IF NOT EXISTS idx_chunk ON chunks(fid);
        """
    )
    cols = {r[1] for r in DB.execute("PRAGMA table_info(messages)")}
    for c in ("attachments", "files", "links"):
        if c not in cols:
            DB.execute(f"ALTER TABLE messages ADD COLUMN {c} TEXT")
    DB.commit()


def q(sql, args=()):
    with LOCK:
        cur = DB.execute(sql, args)
        DB.commit()
        return [dict(r) for r in cur.fetchall()]


def get_settings():
    rows = q("SELECT v FROM kv WHERE k='settings'")
    return deep_merge(DEFAULTS, json.loads(rows[0]["v"]) if rows else {})


def save_settings(patch):
    merged = deep_merge(get_settings(), patch)
    q("INSERT OR REPLACE INTO kv(k,v) VALUES('settings',?)", (json.dumps(merged),))
    return merged


def uid():
    return uuid.uuid4().hex


def key_chat(S):
    return S["chat"]["api_key"] or os.environ.get("NVIDIA_API_KEY", "")


def key_embed(S):
    return S["embeddings"]["api_key"] or S["chat"]["api_key"] or os.environ.get("NVIDIA_API_KEY", "")


def key_search(S):
    return S["search"]["api_key"] or os.environ.get("TAVILY_API_KEY", "")


# ───────────────────────── LLM ─────────────────────────
class ThinkFilter:
    """Strips <think>...</think> blocks from a token stream."""

    def __init__(self):
        self.buf, self.in_think = "", False

    def feed(self, t):
        self.buf += t
        out = ""
        while True:
            if self.in_think:
                i = self.buf.find("</think>")
                if i == -1:
                    self.buf = self.buf[-7:]
                    return out
                self.buf = self.buf[i + 8:]
                self.in_think = False
            else:
                i = self.buf.find("<think>")
                if i != -1:
                    out += self.buf[:i]
                    self.buf = self.buf[i + 7:]
                    self.in_think = True
                    continue
                keep = 0
                for k in range(min(6, len(self.buf)), 0, -1):
                    if "<think>".startswith(self.buf[-k:]):
                        keep = k
                        break
                out += self.buf[: len(self.buf) - keep]
                self.buf = self.buf[len(self.buf) - keep:]
                return out

    def flush(self):
        out = "" if self.in_think else self.buf
        self.buf = ""
        return out


async def llm_stream(S, messages, model=None, max_tokens=None, temperature=None, thinking=None):
    cfg = S["chat"]
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key_chat(S)}", "Content-Type": "application/json"}
    base = {
        "model": model or cfg["model"],
        "messages": messages,
        "temperature": cfg["temperature"] if temperature is None else temperature,
        "max_tokens": max_tokens or cfg["max_tokens"],
        "stream": True,
    }
    think = cfg["thinking"] if thinking is None else thinking
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as c:
        for attempt in (0, 1):
            body = dict(base)
            if attempt == 0:  # NVIDIA-hosted Nemotron toggle; retried without if the endpoint rejects it
                body["chat_template_kwargs"] = {"enable_thinking": bool(think)}
            async with c.stream("POST", url, headers=headers, json=body) as r:
                if r.status_code == 400 and attempt == 0:
                    await r.aread()
                    continue
                if r.status_code >= 400:
                    t = (await r.aread()).decode("utf-8", "ignore")[:400]
                    raise RuntimeError(f"Model API error {r.status_code}: {t}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    d = line[5:].strip()
                    if d == "[DONE]":
                        return
                    try:
                        j = json.loads(d)
                    except Exception:
                        continue
                    delta = ((j.get("choices") or [{}])[0].get("delta")) or {}
                    if delta.get("reasoning_content") or delta.get("reasoning"):
                        yield "reasoning", ""
                    if delta.get("content"):
                        yield "content", delta["content"]
                return


async def llm_once(S, messages, max_tokens=300, temperature=0.2):
    tf, out = ThinkFilter(), ""
    async for kind, t in llm_stream(S, messages, max_tokens=max_tokens, temperature=temperature, thinking=False):
        if kind == "content":
            out += tf.feed(t)
    return (out + tf.flush()).strip()


# ───────────────────────── embeddings + vector memory ─────────────────────────
def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def local_embed(text, dim=384):
    """Offline hashed bag-of-words fallback so memory still works without an embeddings endpoint."""
    toks = re.findall(r"\w+", text.lower())
    vec = [0.0] * dim
    for f in toks + [a + "_" + b for a, b in zip(toks, toks[1:])]:
        h = int(hashlib.md5(f.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 64) & 1 else -1.0
    return _norm(vec)


async def embed_many(texts, kind="passage"):
    """Returns (model_tag, [vectors]). Remote endpoint in batches; offline hashed fallback on any failure."""
    S = get_settings()
    e, key = S["embeddings"], key_embed(S)
    if e["base_url"] and key and texts:
        try:
            out = []
            async with httpx.AsyncClient(timeout=60) as c:
                for i in range(0, len(texts), 16):
                    body = {"model": e["model"], "input": [t[:2000] for t in texts[i:i + 16]]}
                    if "nvidia" in e["base_url"]:
                        body.update({"input_type": kind, "truncate": "END"})
                    r = await c.post(e["base_url"].rstrip("/") + "/embeddings", headers={"Authorization": f"Bearer {key}"}, json=body)
                    r.raise_for_status()
                    out += [_norm(d["embedding"]) for d in sorted(r.json()["data"], key=lambda d: d.get("index", 0))]
            return "remote:" + e["model"], out
        except Exception:
            pass
    return "local", [local_embed(t) for t in texts]


async def embed(text, kind="passage"):
    tag, vs = await embed_many([text], kind)
    return tag, vs[0]


async def recall(query, k, min_score):
    if not q("SELECT 1 FROM memories LIMIT 1"):
        return []
    tag, qv = await embed(query, "query")
    scored = []
    for r in q("SELECT text, emb, emb_model FROM memories"):
        if r["emb_model"] != tag:
            continue
        v = json.loads(r["emb"])
        if len(v) != len(qv):
            continue
        s = sum(a * b for a, b in zip(qv, v))
        if s >= min_score:
            scored.append((s, r["text"]))
    scored.sort(reverse=True)
    return [t for _, t in scored[:k]]


async def add_memory(text):
    text = text.strip()
    if not text:
        return None
    tag, v = await embed(text, "passage")
    for r in q("SELECT emb, emb_model FROM memories"):
        if r["emb_model"] == tag:
            o = json.loads(r["emb"])
            if len(o) == len(v) and sum(a * b for a, b in zip(v, o)) > 0.92:
                return None
    mid = uid()
    q("INSERT INTO memories(id,text,emb,emb_model,created) VALUES(?,?,?,?,?)", (mid, text, json.dumps(v), tag, time.time()))
    return mid


EXTRACT_PROMPT = (
    "Extract durable facts or preferences about the USER worth remembering long-term from this exchange "
    "(name, job, location, tools, projects, goals, preferences, constraints). Ignore transient requests and "
    "anything about the assistant. Reply ONLY with a JSON array of short third-person strings, e.g. "
    '["User is a Python developer"]. Reply [] if nothing qualifies.'
)


async def extract_memories(user_text, assistant_text):
    try:
        S = get_settings()
        raw = await llm_once(
            S,
            [
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": f"USER: {user_text[:1500]}\n\nASSISTANT: {assistant_text[:1500]}"},
            ],
            max_tokens=250,
        )
        m = re.search(r"\[.*\]", raw, re.S)
        for fact in (json.loads(m.group(0)) if m else [])[:5]:
            if isinstance(fact, str) and 3 < len(fact) < 300:
                await add_memory(fact)
    except Exception:
        pass


# ───────────────────────── web search (Tavily) ─────────────────────────
ROUTER_PROMPT = (
    "Decide whether answering the user's latest message needs fresh information from the internet: news, prices, "
    "scores, weather, releases, 'latest/current/today', people or products that may have changed, URLs, or facts you "
    "are unsure about. Do NOT search for chit-chat, coding help, math, writing, translation, or timeless knowledge. "
    'Reply ONLY with JSON: {"search": true|false, "query": "<concise web search query>"}. Now: %s.'
)


async def route_search(S, history, now_str):
    try:
        recent = "\n".join(f"{m['role']}: {m['content'][:400]}" for m in history[-4:])
        raw = await llm_once(
            S,
            [{"role": "system", "content": ROUTER_PROMPT % now_str}, {"role": "user", "content": recent}],
            max_tokens=80,
            temperature=0,
        )
        m = re.search(r"\{.*\}", raw, re.S)
        j = json.loads(m.group(0)) if m else {}
        return bool(j.get("search")), (j.get("query") or "").strip()
    except Exception:
        return False, ""


async def tavily(S, query):
    s = S["search"]
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            s["base_url"].rstrip("/") + "/search",
            headers={"Authorization": f"Bearer {key_search(S)}"},
            json={"query": query, "max_results": int(s["max_results"]), "search_depth": "basic"},
        )
        r.raise_for_status()
        return [
            {"title": x.get("title", ""), "url": x.get("url", ""), "content": x.get("content", "")}
            for x in r.json().get("results", [])
        ]


# ───────────────────────── text extraction (uploads + links) ─────────────────────────
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".yaml", ".yml", ".log", ".ini", ".toml", ".cfg", ".env", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".scss", ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".sh", ".bat", ".ps1", ".sql", ".swift", ".kt", ".lua", ".r", ".srt", ".vtt", ".tex", ".svg", ".ics", ".vue", ".gradle"}
IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template", "iframe", "canvas"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.title, self.in_title = [], 0, "", False

    def handle_starttag(self, t, a):
        if t == "title":
            self.in_title = True
        if t in self.SKIP:
            self.skip += 1
        elif t in ("p", "div", "br", "tr", "section", "article", "ul", "ol", "table", "pre", "blockquote", "header", "footer"):
            self.out.append("\n")
        elif t == "li":
            self.out.append("\n- ")
        elif len(t) == 2 and t[0] == "h" and t[1].isdigit():
            self.out.append("\n\n" + "#" * int(t[1]) + " ")

    def handle_endtag(self, t):
        if t == "title":
            self.in_title = False
        if t in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, d):
        if self.in_title:
            self.title += d
        elif not self.skip:
            self.out.append(d)


def html_to_text(html):
    p = _HTMLText()
    try:
        p.feed(html)
    except Exception:
        pass
    text = re.sub(r"[ \t\r\f\v]+", " ", "".join(p.out))
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", re.sub(r" *\n *", "\n", text)).strip()
    return p.title.strip(), text


def decode_text(data):
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(enc)
        except Exception:
            pass
    return data.decode("latin-1", "replace")


def extract_text(name, data, depth=0):
    """Returns (kind, text). Never raises."""
    ext = Path(name).suffix.lower()
    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            r = PdfReader(io.BytesIO(data))
            parts = [f"[Page {i + 1}]\n{p.extract_text() or ''}" for i, p in enumerate(r.pages[:400])]
            text = "\n\n".join(parts)
            if len(text.replace("\n", "").replace("[Page", "").strip()) < 30 * max(1, len(parts)) * 0 + 30:
                text += "\n(Little or no extractable text - this may be a scanned PDF.)"
            return "pdf", text
        if ext == ".docx":
            from docx import Document
            from docx.table import Table
            from docx.text.paragraph import Paragraph
            d = Document(io.BytesIO(data))
            out = []
            for ch in d.element.body.iterchildren():
                if ch.tag.endswith("}p"):
                    p = Paragraph(ch, d)
                    if p.text.strip():
                        out.append(("# " if p.style is not None and p.style.name.startswith("Heading") else "") + p.text)
                elif ch.tag.endswith("}tbl"):
                    for row in Table(ch, d).rows:
                        out.append(" | ".join(c.text.strip() for c in row.cells))
            return "docx", "\n".join(out)
        if ext in (".xlsx", ".xlsm"):
            from openpyxl import load_workbook
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets:
                out.append(f"## Sheet: {ws.title}")
                for n, row in enumerate(ws.iter_rows(values_only=True)):
                    if n >= 5000:
                        out.append("(truncated)")
                        break
                    out.append("\t".join("" if v is None else str(v) for v in row))
            return "xlsx", "\n".join(out)
        if ext == ".pptx":
            from pptx import Presentation
            out = []
            for i, sl in enumerate(Presentation(io.BytesIO(data)).slides, 1):
                out.append(f"## Slide {i}")
                for sh in sl.shapes:
                    if sh.has_text_frame and sh.text_frame.text.strip():
                        out.append(sh.text_frame.text)
                if sl.has_notes_slide and sl.notes_slide.notes_text_frame.text.strip():
                    out.append("Notes: " + sl.notes_slide.notes_text_frame.text)
            return "pptx", "\n".join(out)
        if ext == ".zip":
            z = zipfile.ZipFile(io.BytesIO(data))
            names = [i for i in z.infolist() if not i.is_dir()]
            out = ["Archive contents:"] + [f"- {i.filename} ({i.file_size} bytes)" for i in names[:200]]
            if depth < 1:
                shown = 0
                for i in names:
                    if shown >= 25 or i.file_size > 5_000_000 or Path(i.filename).suffix.lower() in IMG_EXT:
                        continue
                    k, t = extract_text(i.filename, z.read(i), depth + 1)
                    if t.strip() and k not in ("error", "binary"):
                        out.append(f"\n### {i.filename}\n{t[:8000]}")
                        shown += 1
            return "zip", "\n".join(out)
        if ext in (".html", ".htm"):
            title, text = html_to_text(decode_text(data))
            return "html", (f"Title: {title}\n\n" if title else "") + text
        if ext in IMG_EXT:
            return "image", ""
        if ext in TEXT_EXT or b"\x00" not in data[:4096]:
            return "text", decode_text(data)
        return "binary", f"(Binary file '{name}', {len(data)} bytes - contents cannot be read as text.)"
    except Exception as ex:
        return "error", f"(Could not extract '{name}': {ex})"


def safe_name(name, default="file.txt"):
    n = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", Path(str(name or "")).name).strip(" .")
    return (n or default)[:120]


def chunk_text(text, size=1400, overlap=150, cap=400):
    paras, chunks, cur = re.split(r"\n{2,}", text), [], ""
    for p in paras:
        while len(p) > size:
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(p[:size])
            p = p[size - overlap:]
        if len(cur) + len(p) + 2 > size and cur:
            chunks.append(cur)
            cur = cur[-overlap:] + "\n\n" + p
        else:
            cur = (cur + "\n\n" + p) if cur else p
    if cur.strip():
        chunks.append(cur)
    return [c for c in chunks if c.strip()][:cap]


async def retrieve_chunks(fids, query, k=8):
    if not fids:
        return []
    tag, qv = await embed(query, "query")
    marks = ",".join("?" * len(fids))
    scored = []
    for r in q(f"SELECT c.fid, c.idx, c.text, c.emb, c.emb_model, u.name FROM chunks c JOIN uploads u ON u.id=c.fid WHERE c.fid IN ({marks})", tuple(fids)):
        if r["emb_model"] != tag:
            continue
        v = json.loads(r["emb"])
        if len(v) == len(qv):
            scored.append((sum(a * b for a, b in zip(qv, v)), r["name"], r["idx"], r["text"]))
    scored.sort(reverse=True)
    top = sorted(scored[:k], key=lambda x: (x[1], x[2]))
    return [(n, t) for _, n, _, t in top]


# ───────────────────────── link reading ─────────────────────────
URL_RE = re.compile(r"https?://[^\s<>\"'`)\]]+")


def find_urls(text):
    seen, out = set(), []
    for u in URL_RE.findall(text or ""):
        u = u.rstrip(".,;:!?")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:3]


async def fetch_page(url):
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (Zen desktop assistant)", "Accept": "text/html,application/pdf,*/*;q=0.8"}) as c:
            async with c.stream("GET", url) as r:
                if r.status_code >= 400:
                    return {"url": url, "title": url, "text": f"(Could not read this link: HTTP {r.status_code})"}
                ct = r.headers.get("content-type", "").split(";")[0].strip().lower()
                data = b""
                async for chunk in r.aiter_bytes():
                    data += chunk
                    if len(data) > 8_000_000:
                        break
        name = Path(urlparse(url).path).name or "page"
        ext = Path(name).suffix or mimetypes.guess_extension(ct) or ".html"
        if ext in (".htm", ".html") or "html" in ct or not ct:
            title, text = html_to_text(decode_text(data))
        else:
            _, text = await asyncio.to_thread(extract_text, name if Path(name).suffix else name + ext, data)
            title = name
        return {"url": url, "title": (title or url)[:120], "text": text[:20000]}
    except Exception as ex:
        return {"url": url, "title": url, "text": f"(Could not read this link: {str(ex)[:120]})"}


# ───────────────────────── file creation ─────────────────────────
def strip_fence(body):
    b = body.strip("\n")
    m = re.match(r"^\s*```[\w+-]*\n(.*?)\n?```\s*$", b, re.S)
    return m.group(1) if m else b


def md_blocks(text):
    lines, i, out, para = text.replace("\r\n", "\n").split("\n"), 0, [], []

    def flush():
        nonlocal para
        if para:
            out.append(("p", " ".join(para)))
            para = []

    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("```"):
            flush()
            j, buf = i + 1, []
            while j < len(lines) and not lines[j].strip().startswith("```"):
                buf.append(lines[j])
                j += 1
            out.append(("code", "\n".join(buf)))
            i = j + 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush(); out.append(("h", len(m.group(1)), m.group(2))); i += 1; continue
        if re.match(r"^(-{3,}|\*{3,})$", s):
            flush(); out.append(("hr",)); i += 1; continue
        if s.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.match(r"^:?-+:?$", c) for c in row if c):
                    rows.append(row)
                i += 1
            if rows:
                out.append(("table", rows))
            continue
        m = re.match(r"^([-*+]|\d+[.)])\s+(.*)$", s)
        if m:
            flush(); out.append(("li", m.group(2), m.group(1)[0].isdigit())); i += 1; continue
        if not s:
            flush(); i += 1; continue
        para.append(s)
        i += 1
    flush()
    return out


def inline_runs(t):
    runs = []
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`|(?<!\*)\*[^*\n]+\*(?!\*))", t):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) > 4:
            runs.append((part[2:-2], True, False, False))
        elif part.startswith("`") and part.endswith("`") and len(part) > 2:
            runs.append((part[1:-1], False, False, True))
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            runs.append((part[1:-1], False, True, False))
        else:
            runs.append((part, False, False, False))
    return runs


def build_docx(body):
    from docx import Document
    d = Document()

    def runs(p, t):
        for txt, b, i, c in inline_runs(t):
            r = p.add_run(txt)
            r.bold, r.italic = b or None, i or None
            if c:
                r.font.name = "Consolas"

    for b in md_blocks(body):
        k = b[0]
        if k == "h":
            d.add_heading(re.sub(r"[*`]", "", b[2]), level=min(b[1], 4) if b[1] > 1 else 1)
        elif k == "li":
            runs(d.add_paragraph(style="List Number" if b[2] else "List Bullet"), b[1])
        elif k == "p":
            runs(d.add_paragraph(), b[1])
        elif k == "code":
            r = d.add_paragraph().add_run(b[1])
            r.font.name = "Consolas"
        elif k == "table":
            rows, n = b[1], max(len(r) for r in b[1])
            t = d.add_table(rows=len(rows), cols=n)
            t.style = "Table Grid"
            for ri, row in enumerate(rows):
                for ci in range(n):
                    cell = t.cell(ri, ci)
                    cell.text = row[ci] if ci < len(row) else ""
                    if ri == 0:
                        for r in cell.paragraphs[0].runs:
                            r.bold = True
            d.add_paragraph()
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _pdf_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    cands = [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        ("/Library/Fonts/Arial Unicode.ttf", None),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]
    for reg, bd in cands:
        if os.path.exists(reg):
            try:
                pdfmetrics.registerFont(TTFont("ZenSans", reg))
                bold = "ZenSans"
                if bd and os.path.exists(bd):
                    pdfmetrics.registerFont(TTFont("ZenSansB", bd))
                    bold = "ZenSansB"
                pdfmetrics.registerFontFamily("ZenSans", normal="ZenSans", bold=bold, italic="ZenSans", boldItalic=bold)
                return "ZenSans", bold
            except Exception:
                continue
    return "Helvetica", "Helvetica-Bold"


def build_pdf(body):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import HRFlowable, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle
    font, bold = _pdf_fonts()
    base = ParagraphStyle("b", parent=getSampleStyleSheet()["BodyText"], fontName=font, bulletFontName=font, fontSize=10.5, leading=15, spaceAfter=6)
    hs = {n: ParagraphStyle(f"h{n}", parent=base, fontName=bold, fontSize=sz, leading=sz + 5, spaceBefore=10, spaceAfter=6) for n, sz in {1: 22, 2: 17, 3: 14, 4: 12}.items()}
    code = ParagraphStyle("c", parent=base, fontName="Courier", fontSize=9, leading=12, backColor=colors.whitesmoke)

    def rl(t):
        o = ""
        for txt, b, i, c in inline_runs(t):
            x = xml_escape(txt)
            o += f"<b>{x}</b>" if b else f"<i>{x}</i>" if i else f'<font face="Courier">{x}</font>' if c else x
        return o

    story, n = [], 0
    for b in md_blocks(body):
        k = b[0]
        n = n + 1 if k == "li" and b[2] else 0
        if k == "h":
            story.append(Paragraph(rl(b[2]), hs[min(b[1], 4)]))
        elif k == "p":
            story.append(Paragraph(rl(b[1]), base))
        elif k == "li":
            story.append(Paragraph(rl(b[1]), base, bulletText=f"{n}." if b[2] else "•"))
        elif k == "code":
            story += [Preformatted(b[1], code), Spacer(1, 6)]
        elif k == "hr":
            story.append(HRFlowable(width="100%", color=colors.lightgrey))
        elif k == "table":
            w = max(len(r) for r in b[1])
            data = [[Paragraph(rl(r[c] if c < len(r) else ""), base) for c in range(w)] for r in b[1]]
            t = Table(data, repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story += [t, Spacer(1, 8)]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=18 * mm, bottomMargin=18 * mm).build(story or [Paragraph(" ", base)])
    return buf.getvalue()


def _coerce(c):
    c = c.strip()
    if re.fullmatch(r"-?\d+", c) and not (len(c.lstrip("-")) > 1 and c.lstrip("-").startswith("0")):
        return int(c)
    if re.fullmatch(r"-?\d*\.\d+", c):
        return float(c)
    return c


def build_xlsx(body):
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    sheets, name, cur = [], "Sheet1", []
    for ln in body.replace("\r\n", "\n").split("\n"):
        m = re.match(r"^##\s*Sheet:\s*(.+)$", ln.strip())
        if m:
            if any(x.strip() for x in cur):
                sheets.append((name, cur))
            name, cur = re.sub(r"[\[\]:*?/\\]", "", m.group(1)).strip()[:31] or "Sheet", []
        else:
            cur.append(ln)
    if any(x.strip() for x in cur) or not sheets:
        sheets.append((name, cur))
    wb = Workbook()
    wb.remove(wb.active)
    for nm, lines in sheets:
        ws = wb.create_sheet(nm)
        for row in csv.reader(lines):
            ws.append([_coerce(c) for c in row])
        for c in ws[1]:
            c.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for col in ws.columns:
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(60, max(10, max(len(str(c.value or "")) for c in col) + 2))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_pptx(body):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    slides = [s for s in re.split(r"\n\s*---+\s*\n", "\n" + body.replace("\r\n", "\n") + "\n") if s.strip()]
    for idx, sd in enumerate(slides):
        title, items = "", []
        for ln in sd.strip().split("\n"):
            t = ln.strip()
            if not t:
                continue
            if t.startswith("#") and not title:
                title = t.lstrip("#").strip()
            else:
                items.append(re.sub(r"^([-*+]|\d+[.)])\s+", "", t))
        first = idx == 0 and len(slides) > 0
        sl = prs.slides.add_slide(prs.slide_layouts[0 if first else 1])
        sl.shapes.title.text = re.sub(r"[*`]", "", title or f"Slide {idx + 1}")
        sl.shapes.title.left, sl.shapes.title.width = Inches(0.8), Inches(11.7)
        ph = sl.placeholders[1]
        if first:
            sl.shapes.title.top, sl.shapes.title.height = Inches(2.2), Inches(1.6)
            ph.left, ph.top, ph.width, ph.height = Inches(0.8), Inches(4.0), Inches(11.7), Inches(1.5)
            ph.text = re.sub(r"[*`]", "", " ".join(items[:2]))
        else:
            sl.shapes.title.top, sl.shapes.title.height = Inches(0.4), Inches(1.1)
            ph.left, ph.top, ph.width, ph.height = Inches(0.8), Inches(1.7), Inches(11.7), Inches(5.2)
            tf = ph.text_frame
            tf.clear()
            for n, it in enumerate(items):
                p = tf.paragraphs[0] if n == 0 else tf.add_paragraph()
                p.text = re.sub(r"[*`]", "", it)
                p.font.size = Pt(24 if len(items) <= 6 else 18)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def build_file(name, body):
    body = strip_fence(body)
    ext = Path(name).suffix.lower()
    if ext == ".docx":
        return build_docx(body)
    if ext == ".pdf":
        return build_pdf(body)
    if ext in (".xlsx", ".xlsm"):
        return build_xlsx(body)
    if ext == ".pptx":
        return build_pptx(body)
    return body.encode("utf-8-sig" if ext == ".csv" else "utf-8")


def save_generated(name, data, kind="file", **extra):
    fid = uid()
    d = DATA / "files" / fid
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    return {"id": fid, "name": name, "size": len(data), "kind": kind, "mime": mimetypes.guess_type(name)[0] or "application/octet-stream", "path": str(d / name), **extra}


# ───────────────────────── image generation (Pollinations) ─────────────────────────
SIZES = {"landscape": (1280, 720), "portrait": (720, 1280)}


async def gen_image(S, prompt, size=None, w=None, h=None):
    im = S["image"]
    w, h = (w, h) if w else SIZES.get(size or "", (int(im["width"]), int(im["height"])))
    key = im["api_key"] or os.environ.get("POLLINATIONS_API_KEY", "")
    last = "no endpoint configured"
    async with httpx.AsyncClient(timeout=httpx.Timeout(150.0, connect=15.0), follow_redirects=True) as c:
        for base in (im["base_url"], im["fallback_url"]):
            if not base:
                continue
            url = base.rstrip("/") + "/" + quote(prompt[:900], safe="")
            params = {"model": im["model"], "width": w, "height": h, "nologo": "true", "seed": random.randint(1, 10**6)}
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            for attempt in (0, 1):
                try:
                    r = await c.get(url, params=params, headers=headers)
                    if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                        ext = mimetypes.guess_extension(r.headers["content-type"].split(";")[0]) or ".jpg"
                        return r.content, ".jpg" if ext == ".jpe" else ext
                    last = f"HTTP {r.status_code} {r.text[:100]}"
                    if r.status_code not in (429, 500, 502, 503, 504):
                        break
                except Exception as ex:
                    last = str(ex)[:150]
                await asyncio.sleep(2)
    raise RuntimeError(f"Image generation failed ({last}). Check Settings > Tools & files > Image generation.")


async def enhance_prompt(S, text):
    try:
        out = await llm_once(S, [
            {"role": "system", "content": "Rewrite the user's idea as one vivid, detailed English prompt for an image generator (max 70 words): subject, style, lighting, composition, mood. Output only the prompt."},
            {"role": "user", "content": text[:600]},
        ], max_tokens=140, temperature=0.7)
        return out.strip().strip("\"") or text
    except Exception:
        return text


# ───────────────────────── stream tag filter (<zen-file>, <zen-image>) ─────────────────────────
_OPEN = re.compile(r"<zen-(file|image)\b([^>]*)>")


def _attrs(s):
    return {k: v for k, v in re.findall(r'(\w+)\s*=\s*"([^"]*)"', s)}


class TagFilter:
    def __init__(self):
        self.buf, self.cur = "", None

    @staticmethod
    def _keep(buf, pat):
        for k in range(min(len(pat) - 1, len(buf)), 0, -1):
            if buf.endswith(pat[:k]):
                return k
        return 0

    def feed(self, t):
        self.buf += t
        ev = []
        while True:
            if self.cur is None:
                i = self.buf.find("<zen-")
                if i == -1:
                    k = self._keep(self.buf, "<zen-")
                    if len(self.buf) > k:
                        ev.append(("text", self.buf[: len(self.buf) - k]))
                    self.buf = self.buf[len(self.buf) - k:]
                    break
                if i > 0:
                    ev.append(("text", self.buf[:i]))
                    self.buf = self.buf[i:]
                m = _OPEN.match(self.buf)
                if not m:
                    if ">" in self.buf or len(self.buf) > 400:
                        ev.append(("text", self.buf[0]))
                        self.buf = self.buf[1:]
                        continue
                    break
                self.cur = [m.group(1), _attrs(m.group(2)), ""]
                self.buf = self.buf[m.end():]
                ev.append(("start", self.cur[0], self.cur[1]))
            else:
                close = f"</zen-{self.cur[0]}>"
                i = self.buf.find(close)
                if i == -1:
                    k = self._keep(self.buf, close)
                    self.cur[2] += self.buf[: len(self.buf) - k]
                    self.buf = self.buf[len(self.buf) - k:]
                    break
                self.cur[2] += self.buf[:i]
                self.buf = self.buf[i + len(close):]
                ev.append(("end", self.cur[0], self.cur[1], self.cur[2]))
                self.cur = None
        return ev

    def flush(self):
        ev = []
        if self.cur is not None:
            ev.append(("end", self.cur[0], self.cur[1], self.cur[2] + self.buf))
        elif self.buf:
            ev.append(("text", self.buf))
        self.buf, self.cur = "", None
        return ev


# ───────────────────────── prompt building ─────────────────────────
def parse_now(client):
    try:
        return datetime.fromisoformat((client or {}).get("now", "").replace("Z", "+00:00"))
    except Exception:
        return datetime.now()


def part_of_day(h):
    return "morning" if 5 <= h < 12 else "afternoon" if 12 <= h < 17 else "evening" if 17 <= h < 22 else "night"


TOOLS_PROMPT = """You have tools, used by writing special tags in your reply (the app turns them into real files/images; never explain the tags):
{files}{images}"""
FILES_PROMPT = """CREATE FILES: when the user asks for a file/document/spreadsheet/presentation/code file, output:
<zen-file name="report.docx">
content
</zen-file>
Content by extension: .docx, .pdf, .md -> Markdown (# headings, - lists, **bold**, tables); .xlsx -> CSV text (for several sheets start each with a line "## Sheet: Name"; numbers unquoted; formulas like =SUM(B2:B9) allowed); .pptx -> Markdown, slides separated by a line containing only ---, each slide starts with "# Title" then bullet lines; any other extension (txt, csv, json, html, py, js, css, svg, xml, yaml, sql, sh, ics...) -> the raw file content. Never wrap the content in code fences. Always use a meaningful filename. After the tag, briefly say what you made. Only create files when asked.
"""
IMAGES_PROMPT = """GENERATE IMAGES: when the user asks you to draw/create/generate an image, output <zen-image size="square|landscape|portrait">a rich, specific English visual prompt</zen-image> (subject, style, lighting, composition) then one short sentence. Only when asked.
"""


def build_system(S, client, mems, results, query, pages, rag):
    now = parse_now(client)
    p, t = S["profile"], S["tools"]
    parts = [
        "You are Zen, a helpful, honest and concise AI assistant. Answer in the user's language. "
        "Use Markdown when it helps; keep answers tight and warm, never preachy.",
        f"Current local date and time: {now.strftime('%A, %B %d, %Y, %I:%M %p')} "
        f"(timezone: {(client or {}).get('tz', 'unknown')}, part of day: {part_of_day(now.hour)}). "
        "Use this for anything time-relative, and let it shape tone naturally (e.g. a greeting) without being forced.",
    ]
    if t["create_files"] or t["create_images"]:
        parts.append(TOOLS_PROMPT.format(files=FILES_PROMPT if t["create_files"] else "", images=IMAGES_PROMPT if t["create_images"] else ""))
    if p["name"]:
        parts.append(f"The user's name is {p['name']}.")
    if p["about"]:
        parts.append(f"About the user: {p['about']}")
    if p["instructions"]:
        parts.append(f"The user's custom instructions:\n{p['instructions']}")
    if mems:
        parts.append("Things you remember about the user (use only when relevant, never recite them):\n" + "\n".join(f"- {m}" for m in mems))
    if rag:
        parts.append("Relevant excerpts from the user's large attached files (quote/cite the file name when useful):\n\n" + "\n\n".join(f"[{n}]\n{x}" for n, x in rag))
    if results:
        block = "\n\n".join(f"[{i+1}] {r['title']} ({r['url']})\n{r['content'][:900]}" for i, r in enumerate(results))
        parts.append(
            f'Live web search results for "{query}", retrieved just now. Prefer them for current facts and cite as [1], [2]. '
            f"If they do not answer the question, say so.\n\n{block}"
        )
    return "\n\n".join(parts)


def trim(history, budget):
    out, used = [], 0
    for m in reversed(history):
        used += len(m["content"])
        if used > budget and out:
            break
        out.append(m)
    return list(reversed(out))


def sse(type_, **kw):
    return f"data: {json.dumps({'type': type_, **kw})}\n\n"


def spawn(coro):
    t = asyncio.create_task(coro)
    TASKS.add(t)
    t.add_done_callback(TASKS.discard)


async def make_title(S, text):
    try:
        t = await llm_once(
            S,
            [
                {"role": "system", "content": "Write a 2-5 word title for a chat that starts with the user's message. No quotes, no trailing punctuation. Reply with the title only."},
                {"role": "user", "content": text[:500]},
            ],
            max_tokens=24,
        )
        t = t.strip().strip("\"'").splitlines()[0][:60] if t.strip() else ""
        return t or text[:40]
    except Exception:
        return text[:40]


def jl(v, default):
    try:
        return json.loads(v) if v else default
    except Exception:
        return default


def add_msg(cid, role, content, sources=None, attachments=None, files=None, links=None):
    mid = uid()
    q("INSERT INTO messages(id,cid,role,content,sources,attachments,files,links,created) VALUES(?,?,?,?,?,?,?,?,?)",
      (mid, cid, role, content, json.dumps(sources or []), json.dumps(attachments or []), json.dumps(files or []), json.dumps(links or []), time.time()))
    q("UPDATE conversations SET updated=? WHERE id=?", (time.time(), cid))
    return mid


def upload_meta(ids):
    if not ids:
        return []
    rows = {r["id"]: r for r in q(f"SELECT id,name,size,kind,mime,chars,rag FROM uploads WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))}
    return [rows[i] for i in ids if i in rows]


def upload_text(fid):
    p = DATA / "uploads" / fid / "text.txt"
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def upload_path(fid, name):
    return DATA / "uploads" / fid / safe_name(name)


def build_history(cid, vision):
    """Returns (history[{role,content}], rag_file_ids, last_user_images[(mime,path)])."""
    hist, rag_ids, images = [], [], []
    rows = q("SELECT role,content,attachments,files,links FROM messages WHERE cid=? ORDER BY created", (cid,))
    for n, r in enumerate(rows):
        content = r["content"]
        if r["role"] == "user":
            parts = [f'<linked_page url="{l["url"]}" title="{l["title"]}">\n{l["text"]}\n</linked_page>' for l in jl(r["links"], [])]
            last = n == len(rows) - 1
            for a in jl(r["attachments"], []):
                if a.get("rag"):
                    rag_ids.append(a["id"])
                    parts.append(f'(Large file attached: "{a["name"]}", {a["chars"]} characters - relevant excerpts are provided in the system context.)')
                elif a["kind"] == "image":
                    if vision and last:
                        images.append((a.get("mime") or "image/png", upload_path(a["id"], a["name"])))
                    else:
                        parts.append(f'(Image attached: "{a["name"]}" - ' + ("not shown in earlier turns." if vision else "the current model cannot view images.") + ")")
                else:
                    parts.append(f'<attached_file name="{a["name"]}">\n{upload_text(a["id"])}\n</attached_file>')
            content = "\n\n".join(parts + [content]) if parts else content
        else:
            notes = [f"[Created {'image' if f['kind'] == 'image' else 'file'}: {f['name']}]" for f in jl(r["files"], [])]
            content = "\n".join([content] + notes) if notes else content
        hist.append({"role": r["role"], "content": content})
    return hist, rag_ids, images


# ───────────────────────── API ─────────────────────────
app = FastAPI(title="Zen backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/settings")
def api_get_settings():
    return get_settings()


@app.put("/api/settings")
def api_put_settings(patch: dict):
    return save_settings(patch)


@app.get("/api/conversations")
def list_convs():
    return q("SELECT id,title,created,updated FROM conversations ORDER BY updated DESC")


@app.get("/api/conversations/{cid}")
def get_conv(cid: str):
    rows = q("SELECT id,role,content,sources,attachments,files,created FROM messages WHERE cid=? ORDER BY created", (cid,))
    for r in rows:
        r["sources"], r["attachments"], r["files"] = jl(r["sources"], []), jl(r["attachments"], []), jl(r["files"], [])
    return rows


@app.get("/api/conversations/{cid}/export")
def export_conv(cid: str):
    c = q("SELECT title FROM conversations WHERE id=?", (cid,))
    if not c:
        raise HTTPException(404)
    out = [f"# {c[0]['title']}", ""]
    for r in q("SELECT role,content,files FROM messages WHERE cid=? ORDER BY created", (cid,)):
        out.append(f"**{'You' if r['role'] == 'user' else 'Zen'}:**\n\n{r['content']}")
        for f in jl(r["files"], []):
            out.append(f"_(attached output: {f['name']})_")
        out.append("")
    return PlainTextResponse("\n".join(out), headers={"Content-Disposition": f'attachment; filename="{safe_name(c[0]["title"], "chat")}.md"'})


class Rename(BaseModel):
    title: str


@app.patch("/api/conversations/{cid}")
def rename_conv(cid: str, body: Rename):
    q("UPDATE conversations SET title=? WHERE id=?", (body.title.strip()[:80] or "New chat", cid))
    return {"ok": True}


@app.delete("/api/conversations/{cid}")
def delete_conv(cid: str):
    q("DELETE FROM messages WHERE cid=?", (cid,))
    q("DELETE FROM conversations WHERE id=?", (cid,))
    return {"ok": True}


@app.get("/api/memories")
def list_memories():
    return q("SELECT id,text,created FROM memories ORDER BY created DESC")


class MemIn(BaseModel):
    text: str


@app.post("/api/memories")
async def post_memory(body: MemIn):
    return {"id": await add_memory(body.text)}


@app.delete("/api/memories/{mid}")
def delete_memory(mid: str):
    q("DELETE FROM memories WHERE id=?", (mid,))
    return {"ok": True}


@app.delete("/api/memories")
def clear_memories():
    q("DELETE FROM memories")
    return {"ok": True}


@app.post("/api/upload")
async def upload(request: Request, name: str):
    data = await request.body()
    if len(data) > 150_000_000:
        raise HTTPException(413, "File too large (max 150 MB)")
    fid, fname = uid(), safe_name(name)
    d = DATA / "uploads" / fid
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_bytes(data)
    kind, text = await asyncio.to_thread(extract_text, fname, data)
    (d / "text.txt").write_text(text, encoding="utf-8")
    rag = 1 if len(text) > RAG_THRESHOLD else 0
    if rag:
        chunks = chunk_text(text)
        tag, vecs = await embed_many(chunks, "passage")
        for i, (c, v) in enumerate(zip(chunks, vecs)):
            q("INSERT INTO chunks(id,fid,idx,text,emb,emb_model) VALUES(?,?,?,?,?,?)", (uid(), fid, i, c, json.dumps(v), tag))
    mime = mimetypes.guess_type(fname)[0] or "application/octet-stream"
    q("INSERT INTO uploads(id,name,size,kind,mime,chars,rag,created) VALUES(?,?,?,?,?,?,?,?)", (fid, fname, len(data), kind, mime, len(text), rag, time.time()))
    return {"id": fid, "name": fname, "size": len(data), "kind": kind, "mime": mime, "chars": len(text), "rag": rag}


def _serve(folder, fid, name):
    p = DATA / folder / fid / safe_name(name)
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type=mimetypes.guess_type(p.name)[0] or "application/octet-stream", filename=p.name if folder == "files" else None, content_disposition_type="inline" if mimetypes.guess_type(p.name)[0] in ("image/png", "image/jpeg", "image/webp", "image/gif") else "attachment")


@app.get("/api/files/{fid}/{name}")
def get_file(fid: str, name: str):
    return _serve("files", fid, name)


@app.get("/api/uploads/{fid}/{name}")
def get_upload(fid: str, name: str):
    return _serve("uploads", fid, name)


class TestIn(BaseModel):
    target: str  # chat | embeddings | search | image


@app.post("/api/test")
async def api_test(body: TestIn):
    S = get_settings()
    try:
        if body.target == "chat":
            out = await llm_once(S, [{"role": "user", "content": "Reply with the single word: ok"}], max_tokens=16)
            return {"ok": True, "detail": f"Model replied: {out[:60] or '(empty)'}"}
        if body.target == "embeddings":
            tag, v = await embed("connection test", "query")
            return {"ok": tag != "local", "detail": f"{tag} ({len(v)} dims)" + ("" if tag != "local" else " - remote endpoint unreachable, using offline fallback")}
        if body.target == "search":
            if not key_search(S):
                return {"ok": False, "detail": "No Tavily API key set"}
            r = await tavily(S, "connection test")
            return {"ok": True, "detail": f"{len(r)} results"}
        if body.target == "image":
            data, ext = await gen_image(S, "a small red circle on white background", w=256, h=256)
            return {"ok": True, "detail": f"Generated {len(data) // 1024} KB image ({ext})"}
        return {"ok": False, "detail": "Unknown target"}
    except Exception as ex:
        return {"ok": False, "detail": str(ex)[:300]}


class ChatReq(BaseModel):
    conversation_id: str | None = None
    message: str = ""
    model: str | None = None
    client: dict = {}
    attachments: list[str] = []
    mode: str = "chat"  # chat | image
    search: bool = False  # force a web search for this turn
    regenerate: bool = False
    truncate_from: str | None = None  # edit: drop this message and everything after


@app.post("/api/chat")
async def chat(req: ChatReq):
    S = get_settings()
    if req.mode != "image" and not key_chat(S):
        raise HTTPException(400, "No API key set. Open Settings > Models and add your key.")
    cid, new = req.conversation_id, False
    if not cid or not q("SELECT 1 FROM conversations WHERE id=?", (cid,)):
        cid, new = cid or uid(), True
        q("INSERT INTO conversations(id,title,created,updated) VALUES(?,?,?,?)", (cid, "New chat", time.time(), time.time()))
    atts = upload_meta(req.attachments)
    if req.regenerate:
        last = q("SELECT id,content,created FROM messages WHERE cid=? AND role='user' ORDER BY created DESC LIMIT 1", (cid,))
        if not last:
            raise HTTPException(400, "Nothing to regenerate")
        q("DELETE FROM messages WHERE cid=? AND created>?", (cid, last[0]["created"]))
        user_id, user_text = last[0]["id"], last[0]["content"]
    else:
        if req.truncate_from:
            old = q("SELECT created,attachments FROM messages WHERE id=? AND cid=?", (req.truncate_from, cid))
            if old:
                if not atts:
                    atts = jl(old[0]["attachments"], [])
                q("DELETE FROM messages WHERE cid=? AND created>=?", (cid, old[0]["created"]))
        user_text = req.message
        user_id = add_msg(cid, "user", user_text, attachments=atts)

    async def gen():
        full, sources, files, thinking_sent, saved = "", [], [], False, False
        title_task = asyncio.create_task(make_title(S, user_text)) if new and user_text else None

        def save_reply():
            nonlocal saved
            if saved or not (full.strip() or files):
                return
            saved = True
            add_msg(cid, "assistant", full, sources=sources, files=files)

        async def finish():
            if title_task:
                title = await title_task
                q("UPDATE conversations SET title=? WHERE id=?", (title, cid))
                yield sse("title", title=title)

        try:
            yield sse("meta", conversation_id=cid)
            now_str = parse_now(req.client).strftime("%A %Y-%m-%d %H:%M")

            # ── image mode: skip the chat model, go straight to Pollinations
            if req.mode == "image":
                yield sse("status", text="Creating image…")
                prompt = await enhance_prompt(S, user_text) if S["image"]["enhance"] and key_chat(S) else user_text
                data, ext = await gen_image(S, prompt)
                meta = save_generated(f"image-{int(time.time())}{ext}", data, kind="image", prompt=prompt)
                files.append(meta)
                yield sse("file", file=meta)
                full = "Here's your image."
                yield sse("token", text=full)
                save_reply()
                async for e in finish():
                    yield e
                yield sse("done")
                return

            # ── link reading
            if S["tools"]["read_links"]:
                if not req.regenerate:
                    urls = find_urls(user_text)
                    if urls:
                        yield sse("status", text="Reading link…" if len(urls) == 1 else "Reading links…")
                        pages = await asyncio.gather(*[fetch_page(u) for u in urls])
                        q("UPDATE messages SET links=? WHERE id=?", (json.dumps(pages), user_id))
                pages = jl((q("SELECT links FROM messages WHERE id=?", (user_id,)) or [{}])[0].get("links"), [])
                sources = [{"title": p["title"], "url": p["url"]} for p in pages]
                if sources:
                    yield sse("sources", items=sources)

            cur_model = req.model or S["chat"]["model"]
            vision = any(m["id"] == cur_model and m.get("vision") for m in S["chat"]["models"])
            hist, rag_ids, images = build_history(cid, vision)

            mems = []
            if S["memory"]["enabled"]:
                mems = await recall(user_text, int(S["memory"]["top_k"]), float(S["memory"]["min_score"]))
            rag = []
            if rag_ids:
                yield sse("status", text="Reading your files…")
                rag = await retrieve_chunks(list(dict.fromkeys(rag_ids)), user_text)

            results, query, sm = [], user_text, S["search"]
            if (sm["mode"] != "off" or req.search) and key_search(S):
                do = sm["mode"] == "always" or req.search
                if not do and sm["mode"] == "auto":
                    yield sse("status", text="Thinking…")
                    do, rq = await route_search(S, hist, now_str)
                    query = rq or user_text
                if do:
                    yield sse("status", text="Searching the web…")
                    try:
                        results = await tavily(S, query)
                        sources = sources + [{"title": r["title"], "url": r["url"]} for r in results]
                        yield sse("sources", items=sources)
                    except Exception as ex:
                        yield sse("status", text=f"Search failed ({str(ex)[:60]}), answering without it…")
            elif req.search:
                yield sse("status", text="Add a Tavily key in Settings to search the web…")

            system = build_system(S, req.client, mems, results, query, None, rag)
            msgs = [{"role": "system", "content": system}] + trim(hist, int(S["context"]["max_chars"]))
            if images and msgs[-1]["role"] == "user":
                parts = [{"type": "text", "text": msgs[-1]["content"] or "Describe this image."}]
                for mime, path in images:
                    try:
                        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"}})
                    except Exception:
                        pass
                msgs[-1] = {"role": "user", "content": parts}
            yield sse("status", text="")

            tf, tags = ThinkFilter(), TagFilter()

            async def handle(events):
                nonlocal full
                for ev in events:
                    if ev[0] == "text":
                        if ev[1]:
                            full += ev[1]
                            yield sse("token", text=ev[1])
                    elif ev[0] == "start":
                        yield sse("file_start", kind=ev[1], name=ev[2].get("name", ""))
                    else:
                        _, kind, attrs, body = ev
                        try:
                            if kind == "image":
                                if not S["tools"]["create_images"]:
                                    continue
                                yield sse("status", text="Generating image…")
                                data, ext = await gen_image(S, body.strip(), attrs.get("size"))
                                meta = save_generated(f"image-{int(time.time())}{ext}", data, kind="image", prompt=body.strip())
                            else:
                                if not S["tools"]["create_files"]:
                                    continue
                                name = safe_name(attrs.get("name"), "file.txt")
                                meta = save_generated(name, await asyncio.to_thread(build_file, name, body))
                            files.append(meta)
                            yield sse("status", text="")
                            yield sse("file", file=meta)
                        except Exception as ex:
                            yield sse("file_error", message=f"Could not create {attrs.get('name') or kind}: {str(ex)[:160]}")

            async for kind, t in llm_stream(S, msgs, model=req.model):
                if kind == "reasoning":
                    if not thinking_sent:
                        thinking_sent = True
                        yield sse("status", text="Thinking…")
                    continue
                out = tf.feed(t)
                if out:
                    if thinking_sent:
                        thinking_sent = False
                        yield sse("status", text="")
                    async for e in handle(tags.feed(out)):
                        yield e
            async for e in handle(tags.feed(tf.flush()) + tags.flush()):
                yield e
            save_reply()
            async for e in finish():
                yield e
            yield sse("done")
            if S["memory"]["enabled"] and user_text:
                spawn(extract_memories(user_text, full))
        except asyncio.CancelledError:
            save_reply()
            raise
        except Exception as ex:
            save_reply()
            yield sse("error", message=str(ex))

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def main():
    global DATA
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data-dir", default=os.environ.get("ZEN_DATA", str(Path.home() / ".zen")))
    a = ap.parse_args()
    DATA = Path(a.data_dir)
    DATA.mkdir(parents=True, exist_ok=True)
    db_init(DATA / "zen.db")
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning", log_config=None)


if __name__ == "__main__":
    main()
