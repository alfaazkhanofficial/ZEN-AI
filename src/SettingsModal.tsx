import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from './api';
import type { Memory, Settings } from './api';
import { Close } from './icons';

type Patch = (p: any) => void;
const TABS = ['General', 'Personalization', 'Models', 'Memory & context', 'Web search', 'Tools & files'];

const Row = ({ label, desc, children }: { label: string; desc?: string; children: ReactNode }) => (
  <div className="row"><div className="row-l"><div>{label}</div>{desc && <div className="row-d">{desc}</div>}</div><div className="row-c">{children}</div></div>
);
const Toggle = ({ on, set }: { on: boolean; set: (v: boolean) => void }) => (
  <button className={'toggle' + (on ? ' on' : '')} onClick={() => set(!on)} role="switch" aria-checked={on}><span /></button>
);
const Field = ({ label, children }: { label: string; children: ReactNode }) => <label className="field"><span>{label}</span>{children}</label>;

function Test({ target }: { target: 'chat' | 'embeddings' | 'search' | 'image' }) {
  const [res, setRes] = useState<{ ok: boolean; detail: string } | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="test">
      <button className="btn" disabled={busy} onClick={async () => { setBusy(true); setRes(null); setTimeout(async () => { setRes(await api.test(target).catch((e) => ({ ok: false, detail: String(e) }))); setBusy(false); }, 700); }}>
        {busy ? 'Testing…' : 'Test connection'}
      </button>
      {res && <span className={res.ok ? 'ok' : 'bad'}>{res.detail}</span>}
    </div>
  );
}

export default function SettingsModal({ s, patch, onClose, tab: initial }: { s: Settings; patch: Patch; onClose: () => void; tab: string }) {
  const [tab, setTab] = useState(TABS.includes(initial) ? initial : 'General');
  const [mems, setMems] = useState<Memory[]>([]);
  const [newMem, setNewMem] = useState('');
  const loadMems = () => api.memories().then(setMems).catch(() => {});
  useEffect(() => { loadMems(); }, []);
  useEffect(() => { const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose(); window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k); }, [onClose]);

  const setModels = (models: Settings['chat']['models']) => patch({ chat: { models, model: models.some((m) => m.id === s.chat.model) ? s.chat.model : models[0]?.id ?? '' } });

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <nav className="modal-nav">
          <button className="icon-btn close" onClick={onClose}><Close /></button>
          {TABS.map((t) => <button key={t} className={'nav-item' + (t === tab ? ' active' : '')} onClick={() => setTab(t)}>{t}</button>)}
        </nav>
        <section className="modal-body">
          <h2>{tab}</h2>
          {tab === 'General' && (
            <>
              <Row label="Theme">
                <select value={s.theme} onChange={(e) => patch({ theme: e.target.value })}>
                  <option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option>
                </select>
              </Row>
              <Row label="Name" desc="Used for greetings and personalisation.">
                <input value={s.profile.name} onChange={(e) => patch({ profile: { name: e.target.value } })} placeholder="Your name" />
              </Row>
            </>
          )}
          {tab === 'Personalization' && (
            <>
              <Field label="About you"><textarea rows={4} value={s.profile.about} placeholder="Anything Zen should know about you" onChange={(e) => patch({ profile: { about: e.target.value } })} /></Field>
              <Field label="Custom instructions"><textarea rows={5} value={s.profile.instructions} placeholder="How should Zen respond?" onChange={(e) => patch({ profile: { instructions: e.target.value } })} /></Field>
            </>
          )}
          {tab === 'Models' && (
            <>
              <Field label="Chat endpoint (OpenAI-compatible)"><input value={s.chat.base_url} onChange={(e) => patch({ chat: { base_url: e.target.value } })} /></Field>
              <Field label="API key"><input type="password" value={s.chat.api_key} placeholder="nvapi-…" onChange={(e) => patch({ chat: { api_key: e.target.value } })} /></Field>
              <div className="field"><span>Models</span>
                {s.chat.models.map((m, i) => (
                  <div className="model-row" key={i}>
                    <input value={m.label} placeholder="Label" onChange={(e) => setModels(s.chat.models.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} />
                    <input value={m.id} placeholder="Model id" onChange={(e) => {
                      const models = s.chat.models.map((x, j) => (j === i ? { ...x, id: e.target.value } : x));
                      patch({ chat: { models, model: s.chat.model === m.id ? e.target.value : s.chat.model } });
                    }} />
                    <label className="vis" title="Model can see images"><input type="checkbox" checked={!!m.vision} onChange={(e) => setModels(s.chat.models.map((x, j) => (j === i ? { ...x, vision: e.target.checked } : x)))} /> Vision</label>
                    <button className="btn" onClick={() => setModels(s.chat.models.filter((_, j) => j !== i))} disabled={s.chat.models.length < 2}>Remove</button>
                  </div>
                ))}
                <button className="btn" onClick={() => setModels([...s.chat.models, { id: '', label: 'New model' }])}>Add model</button>
              </div>
              <Row label="Active model">
                <select value={s.chat.model} onChange={(e) => patch({ chat: { model: e.target.value } })}>
                  {s.chat.models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                </select>
              </Row>
              <Row label="Temperature"><input type="number" step="0.1" min="0" max="2" value={s.chat.temperature} onChange={(e) => patch({ chat: { temperature: Number(e.target.value) } })} /></Row>
              <Row label="Max output tokens"><input type="number" step="256" min="64" value={s.chat.max_tokens} onChange={(e) => patch({ chat: { max_tokens: Number(e.target.value) } })} /></Row>
              <Row label="Reasoning" desc="Let the model think before answering (slower)."><Toggle on={s.chat.thinking} set={(v) => patch({ chat: { thinking: v } })} /></Row>
              <Test target="chat" />
            </>
          )}
          {tab === 'Memory & context' && (
            <>
              <Row label="Memory" desc="Zen saves durable facts about you and recalls them when relevant."><Toggle on={s.memory.enabled} set={(v) => patch({ memory: { enabled: v } })} /></Row>
              <Row label="Memories recalled per message"><input type="number" min="1" max="20" value={s.memory.top_k} onChange={(e) => patch({ memory: { top_k: Number(e.target.value) } })} /></Row>
              <Row label="Conversation context (characters)" desc="How much recent chat history is sent to the model."><input type="number" step="1000" min="2000" value={s.context.max_chars} onChange={(e) => patch({ context: { max_chars: Number(e.target.value) } })} /></Row>
              <Field label="Embeddings endpoint"><input value={s.embeddings.base_url} onChange={(e) => patch({ embeddings: { base_url: e.target.value } })} /></Field>
              <Field label="Embedding model"><input value={s.embeddings.model} onChange={(e) => patch({ embeddings: { model: e.target.value } })} /></Field>
              <Field label="Embeddings API key (blank = use chat key)"><input type="password" value={s.embeddings.api_key} onChange={(e) => patch({ embeddings: { api_key: e.target.value } })} /></Field>
              <Test target="embeddings" />
              <div className="field"><span>Saved memories ({mems.length})</span>
                <div className="mem-add">
                  <input value={newMem} placeholder="Add a memory" onChange={(e) => setNewMem(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && newMem.trim()) { api.addMemory(newMem).then(loadMems); setNewMem(''); } }} />
                  <button className="btn" onClick={() => { if (newMem.trim()) { api.addMemory(newMem).then(loadMems); setNewMem(''); } }}>Add</button>
                </div>
                <div className="mem-list">
                  {mems.map((m) => <div className="mem" key={m.id}><span>{m.text}</span><button className="btn" onClick={() => api.delMemory(m.id).then(loadMems)}>Delete</button></div>)}
                </div>
                {mems.length > 0 && <button className="btn danger" onClick={() => confirm('Delete all memories?') && api.clearMemories().then(loadMems)}>Clear all memories</button>}
              </div>
            </>
          )}
          {tab === 'Web search' && (
            <>
              <Row label="Search mode" desc="Auto lets the model decide per query whether the internet is needed.">
                <select value={s.search.mode} onChange={(e) => patch({ search: { mode: e.target.value } })}>
                  <option value="auto">Auto</option><option value="always">Always</option><option value="off">Off</option>
                </select>
              </Row>
              <Field label="Tavily API key"><input type="password" value={s.search.api_key} placeholder="tvly-…" onChange={(e) => patch({ search: { api_key: e.target.value } })} /></Field>
              <Field label="Tavily endpoint"><input value={s.search.base_url} onChange={(e) => patch({ search: { base_url: e.target.value } })} /></Field>
              <Row label="Results per search"><input type="number" min="1" max="10" value={s.search.max_results} onChange={(e) => patch({ search: { max_results: Number(e.target.value) } })} /></Row>
              <Test target="search" />
            </>
          )}
          {tab === 'Tools & files' && (
            <>
              <Row label="Read links" desc="Fetch and read any URL you paste in a message (pages, PDFs, docs)."><Toggle on={s.tools.read_links} set={(v) => patch({ tools: { read_links: v } })} /></Row>
              <Row label="Create files" desc="Zen can make .docx, .xlsx, .pptx, .pdf and any text/code file."><Toggle on={s.tools.create_files} set={(v) => patch({ tools: { create_files: v } })} /></Row>
              <Row label="Create images in chat" desc="Zen can generate images when you ask (or use + → Create image)."><Toggle on={s.tools.create_images} set={(v) => patch({ tools: { create_images: v } })} /></Row>
              <h3 className="sub">Image generation (Pollinations AI)</h3>
              <Field label="Endpoint"><input value={s.image.base_url} onChange={(e) => patch({ image: { base_url: e.target.value } })} /></Field>
              <Field label="Fallback endpoint"><input value={s.image.fallback_url} onChange={(e) => patch({ image: { fallback_url: e.target.value } })} /></Field>
              <Field label="API key (optional, from enter.pollinations.ai)"><input type="password" value={s.image.api_key} onChange={(e) => patch({ image: { api_key: e.target.value } })} /></Field>
              <Row label="Image model"><input list="img-models" value={s.image.model} onChange={(e) => patch({ image: { model: e.target.value } })} /><datalist id="img-models"><option value="flux" /><option value="turbo" /><option value="gptimage" /><option value="kontext" /><option value="seedream" /></datalist></Row>
              <Row label="Default size (px)"><span className="dims"><input type="number" step="64" min="256" value={s.image.width} onChange={(e) => patch({ image: { width: Number(e.target.value) } })} /><input type="number" step="64" min="256" value={s.image.height} onChange={(e) => patch({ image: { height: Number(e.target.value) } })} /></span></Row>
              <Row label="Enhance prompts" desc="Let the chat model expand short ideas before generating (image mode)."><Toggle on={s.image.enhance} set={(v) => patch({ image: { enhance: v } })} /></Row>
              <Test target="image" />
            </>
          )}
        </section>
      </div>
    </div>
  );
}
