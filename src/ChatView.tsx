import { useCallback, useEffect, useRef, useState } from 'react';
import { api, exportUrl, fileUrl, fmtSize, openExternal, openPath } from './api';
import type { Attachment, FileMeta, Msg, Settings } from './api';
import Markdown from './Markdown';
import { ArrowDown, ArrowUp, Check, Chevron, Clip, Close, Compose, Copy, Download, Export, FileIcon, Globe, ImageIcon, Pencil, Plus, Refresh, SidebarIcon, Stop } from './icons';

export interface SendOpts { attachments?: Attachment[]; mode?: 'chat' | 'image'; search?: boolean; regenerate?: boolean; truncateFrom?: string }

interface Props {
  msgs: Msg[]; streaming: boolean; status: string; settings: Settings; sidebarOpen: boolean; activeId: string | null;
  onSend: (t: string, o?: SendOpts) => void; onStop: () => void; onModel: (id: string) => void; onRegenerate: () => void;
  onEdit: (id: string, text: string) => void; onSettings: (tab?: string) => void; onToggleSidebar: () => void; onNew: () => void;
}
interface Pending { key: string; name: string; size: number; preview?: string; att?: Attachment; error?: string }

function greeting(name: string) {
  if (!name) return 'What can I help with?';
  const h = new Date().getHours();
  return `Good ${h >= 5 && h < 12 ? 'morning' : h >= 12 && h < 17 ? 'afternoon' : 'evening'}, ${name}`;
}
const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return u; } };
const isTmp = (id: string) => id.startsWith('tmp-');
const SUGGESTIONS: { label: string; text?: string; mode?: 'image' }[] = [
  { label: 'Summarize a link', text: 'Summarize this article: https://' },
  { label: 'Create an image', mode: 'image' },
  { label: 'Make a spreadsheet', text: 'Create an Excel monthly budget tracker with example data and formulas' },
  { label: 'Explain something', text: 'Explain how neural networks learn, in simple terms' },
];

function ModelPicker({ s, onModel, onSettings }: { s: Settings; onModel: (id: string) => void; onSettings: (t?: string) => void }) {
  const [open, setOpen] = useState(false);
  const cur = s.chat.models.find((m) => m.id === s.chat.model);
  return (
    <div className="picker">
      <button className="picker-btn" onClick={() => setOpen(!open)}><b>Zen</b> <span className="muted">{cur?.label ?? s.chat.model}</span> <Chevron /></button>
      {open && (
        <>
          <div className="scrim" onClick={() => setOpen(false)} />
          <div className="menu pop">
            {s.chat.models.map((m) => (
              <button key={m.id} className="menu-item" onClick={() => { onModel(m.id); setOpen(false); }}>
                <span><div>{m.label}</div><div className="menu-sub">{m.id}{m.vision ? ' · vision' : ''}</div></span>
                {m.id === s.chat.model && <Check />}
              </button>
            ))}
            <div className="menu-sep" />
            <button className="menu-item" onClick={() => { setOpen(false); onSettings('Models'); }}>Configure models…</button>
          </div>
        </>
      )}
    </div>
  );
}

function FileCard({ f }: { f: FileMeta }) {
  const ext = f.name.split('.').pop()?.toUpperCase() ?? 'FILE';
  return (
    <div className="filecard">
      <div className="fc-icon"><FileIcon /></div>
      <div className="fc-info"><div className="fc-name">{f.name}</div><div className="fc-sub">{ext} · {fmtSize(f.size)}</div></div>
      {window.zen && <button className="btn" onClick={() => openPath(f.path)}>Open</button>}
      <a className="btn" href={fileUrl(f)} download={f.name}><Download /> Save</a>
    </div>
  );
}

function ImageCard({ f, onOpen }: { f: FileMeta; onOpen: (f: FileMeta) => void }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <div className={'imgcard' + (loaded ? ' loaded' : '')} onClick={() => onOpen(f)}>
      <img src={fileUrl(f)} alt={f.prompt || f.name} onLoad={() => setLoaded(true)} />
      <a className="img-dl" href={fileUrl(f)} download={f.name} title="Save image" onClick={(e) => e.stopPropagation()}><Download /></a>
    </div>
  );
}

function AttChip({ a, onRemove }: { a: { name: string; size: number; preview?: string; error?: string; busy?: boolean }; onRemove?: () => void }) {
  return (
    <div className={'attchip' + (a.error ? ' err' : '')} title={a.error || a.name}>
      {a.preview ? <img src={a.preview} alt="" /> : <span className="att-ic"><FileIcon /></span>}
      <span className="att-txt"><span className="att-name">{a.name}</span><span className="att-sub">{a.error ? a.error : a.busy ? 'Reading…' : fmtSize(a.size)}</span></span>
      {a.busy && <span className="spin" />}
      {onRemove && <button className="att-x" onClick={onRemove}><Close /></button>}
    </div>
  );
}

function Message({ m, last, streaming, status, canRegen, onRegen, onEdit, onImage }: {
  m: Msg; last: boolean; streaming: boolean; status: string; canRegen: boolean;
  onRegen: () => void; onEdit: (id: string, t: string) => void; onImage: (f: FileMeta) => void;
}) {
  const [copied, setCopied] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const copy = () => { navigator.clipboard.writeText(m.content); setCopied(true); setTimeout(() => setCopied(false), 1500); };

  if (m.role === 'user') {
    return (
      <div className="msg user">
        {(m.attachments?.length ?? 0) > 0 && (
          <div className="u-atts">
            {m.attachments!.map((a) => a.kind === 'image'
              ? <img key={a.id} className="u-img" src={fileUrl(a, 'uploads')} alt={a.name} />
              : <AttChip key={a.id} a={a} />)}
          </div>
        )}
        {editing ? (
          <div className="edit-box">
            <textarea autoFocus value={draft} rows={Math.min(8, draft.split('\n').length + 1)} onChange={(e) => setDraft(e.target.value)} />
            <div className="edit-actions">
              <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
              <button className="btn primary" disabled={!draft.trim()} onClick={() => { setEditing(false); onEdit(m.id, draft.trim()); }}>Send</button>
            </div>
          </div>
        ) : (
          <>
            {m.content && <div className="u-bubble">{m.content}</div>}
            {!streaming && !isTmp(m.id) && (
              <div className="actions user-actions">
                <button title="Edit" onClick={() => { setDraft(m.content); setEditing(true); }}><Pencil /></button>
                <button title="Copy" onClick={copy}>{copied ? <Check /> : <Copy />}</button>
              </div>
            )}
          </>
        )}
      </div>
    );
  }
  const live = last && streaming;
  const images = (m.files ?? []).filter((f) => f.kind === 'image');
  const files = (m.files ?? []).filter((f) => f.kind !== 'image');
  return (
    <div className="msg assistant">
      {live && (status || (!m.content && !m.pending)) && <div className="shimmer">{status || 'Thinking…'}</div>}
      {m.content && <Markdown text={m.content} />}
      {live && m.pending && <div className="filecard skeleton"><div className="fc-icon"><FileIcon /></div><div className="fc-info"><div className="fc-name">{m.pending}</div><div className="fc-sub shimmer">Creating…</div></div></div>}
      {files.map((f) => <FileCard key={f.id} f={f} />)}
      {images.length > 0 && <div className="imgrow">{images.map((f) => <ImageCard key={f.id} f={f} onOpen={onImage} />)}</div>}
      {m.error && <div className="err">{m.error}</div>}
      {m.sources.length > 0 && (
        <div className="sources">
          <span className="src-label"><Globe /> Sources</span>
          {m.sources.map((s, i) => (
            <a key={i} className="src" title={s.title} href={s.url} onClick={(e) => { e.preventDefault(); openExternal(s.url); }}>
              <span className="src-n">{i + 1}</span>{host(s.url)}
            </a>
          ))}
        </div>
      )}
      {!live && (m.content || m.error) && (
        <div className="actions">
          {m.content && <button title="Copy" onClick={copy}>{copied ? <Check /> : <Copy />}</button>}
          {canRegen && <button title="Regenerate" onClick={onRegen}><Refresh /></button>}
        </div>
      )}
    </div>
  );
}

export default function ChatView(p: Props) {
  const [text, setText] = useState('');
  const [pend, setPend] = useState<Pending[]>([]);
  const [mode, setMode] = useState<'chat' | 'image'>('chat');
  const [search, setSearch] = useState(false);
  const [plus, setPlus] = useState(false);
  const [drag, setDrag] = useState(false);
  const [atBottom, setAtBottom] = useState(true);
  const [lightbox, setLightbox] = useState<FileMeta | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const ta = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const dragDepth = useRef(0);
  const empty = p.msgs.length === 0;
  const uploading = pend.some((x) => !x.att && !x.error);

  useEffect(() => { const el = scroller.current; if (el && stick.current) el.scrollTop = el.scrollHeight; }, [p.msgs, p.status]);
  useEffect(() => { const el = ta.current; if (el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 200) + 'px'; } }, [text, empty]);
  useEffect(() => { if (!p.streaming) ta.current?.focus(); }, [empty, p.streaming, p.activeId]);
  useEffect(() => { if (p.activeId === null) { setMode('chat'); setSearch(false); } }, [p.activeId]);
  useEffect(() => { if (!lightbox) return; const k = (e: KeyboardEvent) => e.key === 'Escape' && setLightbox(null); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [lightbox]);

  const addFiles = useCallback((files: File[]) => {
    for (const f of files) {
      const key = Math.random().toString(36).slice(2);
      setPend((l) => [...l, { key, name: f.name || 'pasted-file', size: f.size, preview: f.type.startsWith('image/') ? URL.createObjectURL(f) : undefined }]);
      api.upload(f).then((att) => setPend((l) => l.map((x) => (x.key === key ? { ...x, att } : x))))
        .catch((e) => setPend((l) => l.map((x) => (x.key === key ? { ...x, error: e.message || 'Failed' } : x))));
    }
  }, []);

  const submit = () => {
    if (p.streaming || uploading) return;
    const atts = pend.filter((x) => x.att).map((x) => x.att!);
    if (!text.trim() && !atts.length) return;
    stick.current = true;
    p.onSend(text.trim() || (mode === 'image' ? '' : 'Please analyze the attached file(s).'), { attachments: atts, mode, search });
    setText(''); setPend([]); setMode('chat'); setSearch(false);
  };

  const composer = (
    <div className="composer-wrap">
      <div className="composer-box">
        {(pend.length > 0 || mode === 'image' || search) && (
          <div className="chips">
            {mode === 'image' && <span className="tool-chip"><ImageIcon /> Create image <button onClick={() => setMode('chat')}><Close /></button></span>}
            {search && <span className="tool-chip"><Globe /> Search <button onClick={() => setSearch(false)}><Close /></button></span>}
            {pend.map((x) => <AttChip key={x.key} a={{ ...x, busy: !x.att && !x.error }} onRemove={() => setPend((l) => l.filter((y) => y.key !== x.key))} />)}
          </div>
        )}
        <div className="composer">
          <div className="plus-wrap">
            <button className="icon-btn plus" title="Add" onClick={() => setPlus(!plus)}><Plus /></button>
            {plus && (
              <>
                <div className="scrim" onClick={() => setPlus(false)} />
                <div className="menu pop up">
                  <button className="menu-item" onClick={() => { setPlus(false); picker.current?.click(); }}><span className="mi"><Clip /> Add photos &amp; files</span></button>
                  <button className="menu-item" onClick={() => { setPlus(false); setMode('image'); ta.current?.focus(); }}><span className="mi"><ImageIcon /> Create image</span></button>
                  <button className="menu-item" onClick={() => { setPlus(false); setSearch(true); ta.current?.focus(); }}><span className="mi"><Globe /> Search the web</span></button>
                </div>
              </>
            )}
          </div>
          <input ref={picker} type="file" multiple hidden onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.target.value = ''; }} />
          <textarea ref={ta} rows={1} value={text} placeholder={mode === 'image' ? 'Describe the image you want' : 'Ask anything'} onChange={(e) => setText(e.target.value)}
            onPaste={(e) => { const fs = Array.from(e.clipboardData.files); if (fs.length) { e.preventDefault(); addFiles(fs); } }}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); submit(); } }} />
          {p.streaming
            ? <button className="send" title="Stop" onClick={p.onStop}><Stop /></button>
            : <button className="send" title="Send" disabled={(!text.trim() && !pend.some((x) => x.att)) || uploading} onClick={submit}><ArrowUp /></button>}
        </div>
      </div>
      {!empty && <div className="disclaimer">Zen can make mistakes. Check important info.</div>}
    </div>
  );

  return (
    <main className="main"
      onDragEnter={(e) => { if (e.dataTransfer.types.includes('Files')) { dragDepth.current++; setDrag(true); } }}
      onDragLeave={() => { if (--dragDepth.current <= 0) { dragDepth.current = 0; setDrag(false); } }}
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => { e.preventDefault(); dragDepth.current = 0; setDrag(false); addFiles(Array.from(e.dataTransfer.files)); }}>
      <header className="topbar">
        {!p.sidebarOpen && (
          <>
            <button className="icon-btn" title="Open sidebar (Ctrl+B)" onClick={p.onToggleSidebar}><SidebarIcon /></button>
            <button className="icon-btn" title="New chat (Ctrl+Shift+O)" onClick={p.onNew}><Compose /></button>
          </>
        )}
        <ModelPicker s={p.settings} onModel={p.onModel} onSettings={p.onSettings} />
        <div className="spacer" />
        {p.activeId && !empty && <a className="icon-btn" title="Export chat (Markdown)" href={exportUrl(p.activeId)} download><Export /></a>}
      </header>
      {drag && <div className="dropzone"><div><Clip /> Drop files to add them to the chat</div></div>}
      {empty ? (
        <div className="empty">
          <h1 key={greeting(p.settings.profile.name)}>{greeting(p.settings.profile.name)}</h1>
          {composer}
          <div className="suggest">
            {SUGGESTIONS.map((s, i) => (
              <button key={s.label} className="suggest-chip" style={{ animationDelay: `${120 + i * 60}ms` }}
                onClick={() => { if (s.mode) setMode(s.mode); if (s.text) setText(s.text); ta.current?.focus(); }}>{s.label}</button>
            ))}
          </div>
        </div>
      ) : (
        <>
          <div className="scroller" ref={scroller} onScroll={(e) => { const el = e.currentTarget; const near = el.scrollHeight - el.scrollTop - el.clientHeight < 80; stick.current = near; setAtBottom(near); }}>
            <div className="thread">
              {p.msgs.map((m, i) => (
                <Message key={i} m={m} last={i === p.msgs.length - 1} streaming={p.streaming} status={p.status}
                  canRegen={i === p.msgs.length - 1 && !p.streaming && !isTmp(m.id)} onRegen={p.onRegenerate} onEdit={p.onEdit} onImage={setLightbox} />
              ))}
            </div>
          </div>
          {!atBottom && <button className="to-bottom" title="Scroll to bottom" onClick={() => { const el = scroller.current; if (el) { stick.current = true; el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' }); } }}><ArrowDown /></button>}
          {composer}
        </>
      )}
      {lightbox && (
        <div className="lightbox" onClick={() => setLightbox(null)}>
          <img src={fileUrl(lightbox)} alt={lightbox.name} onClick={(e) => e.stopPropagation()} />
          {lightbox.prompt && <div className="lb-caption" onClick={(e) => e.stopPropagation()}>{lightbox.prompt}</div>}
          <a className="btn lb-save" href={fileUrl(lightbox)} download={lightbox.name} onClick={(e) => e.stopPropagation()}><Download /> Save</a>
        </div>
      )}
    </main>
  );
}
