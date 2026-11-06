export interface Conv { id: string; title: string; created: number; updated: number }
export interface Source { title: string; url: string }
export interface Attachment { id: string; name: string; size: number; kind: string; mime: string; chars: number; rag: number }
export interface FileMeta { id: string; name: string; size: number; kind: 'file' | 'image'; mime: string; path: string; prompt?: string }
export interface Msg { id: string; role: 'user' | 'assistant'; content: string; sources: Source[]; attachments?: Attachment[]; files?: FileMeta[]; error?: string; pending?: string }
export interface ModelDef { id: string; label: string; vision?: boolean }
export interface Settings {
  theme: 'light' | 'dark' | 'system';
  profile: { name: string; about: string; instructions: string };
  chat: { base_url: string; api_key: string; model: string; models: ModelDef[]; temperature: number; max_tokens: number; thinking: boolean };
  embeddings: { base_url: string; api_key: string; model: string };
  memory: { enabled: boolean; top_k: number; min_score: number };
  search: { mode: 'auto' | 'always' | 'off'; base_url: string; api_key: string; max_results: number };
  context: { max_chars: number };
  image: { base_url: string; fallback_url: string; api_key: string; model: string; width: number; height: number; enhance: boolean };
  tools: { read_links: boolean; create_files: boolean; create_images: boolean };
}
export interface Memory { id: string; text: string; created: number }
export type ChatEvent =
  | { type: 'meta'; conversation_id: string }
  | { type: 'file_start'; kind: 'file' | 'image'; name: string }
  | { type: 'file'; file: FileMeta }
  | { type: 'file_error'; message: string }
  | { type: 'status'; text: string }
  | { type: 'sources'; items: Source[] }
  | { type: 'token'; text: string }
  | { type: 'title'; title: string }
  | { type: 'error'; message: string }
  | { type: 'done' };

declare global {
  interface Window { zen?: { apiBase: string; setTheme: (t: string) => void; openExternal: (u: string) => Promise<void>; openPath: (p: string) => Promise<void> } }
}

export const API = window.zen?.apiBase ?? 'http://127.0.0.1:8765';
export const openPath = (p: string) => window.zen?.openPath(p);
export const fileUrl = (f: { id: string; name: string }, kind: 'files' | 'uploads' = 'files') => `${API}/api/${kind}/${f.id}/${encodeURIComponent(f.name)}`;
export const exportUrl = (id: string) => `${API}/api/conversations/${id}/export`;
export const fmtSize = (n: number) => (n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`);
export const openExternal = (u: string) => (window.zen ? window.zen.openExternal(u) : void window.open(u, '_blank'));

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + path, { headers: { 'Content-Type': 'application/json' }, ...init });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export function deepMerge<T>(a: T, b: any): T {
  if (!b || typeof b !== 'object' || Array.isArray(b)) return b ?? a;
  const out: any = { ...(a as any) };
  for (const k of Object.keys(b)) {
    out[k] = b[k] && typeof b[k] === 'object' && !Array.isArray(b[k]) && typeof out[k] === 'object' ? deepMerge(out[k], b[k]) : b[k];
  }
  return out;
}

export const api = {
  settings: () => j<Settings>('/api/settings'),
  putSettings: (p: unknown) => j<Settings>('/api/settings', { method: 'PUT', body: JSON.stringify(p) }),
  convs: () => j<Conv[]>('/api/conversations'),
  messages: (id: string) => j<Msg[]>(`/api/conversations/${id}`),
  rename: (id: string, title: string) => j('/api/conversations/' + id, { method: 'PATCH', body: JSON.stringify({ title }) }),
  del: (id: string) => j('/api/conversations/' + id, { method: 'DELETE' }),
  memories: () => j<Memory[]>('/api/memories'),
  addMemory: (text: string) => j('/api/memories', { method: 'POST', body: JSON.stringify({ text }) }),
  delMemory: (id: string) => j('/api/memories/' + id, { method: 'DELETE' }),
  clearMemories: () => j('/api/memories', { method: 'DELETE' }),
  upload: async (f: File): Promise<Attachment> => {
    const r = await fetch(`${API}/api/upload?name=${encodeURIComponent(f.name)}`, { method: 'POST', body: f });
    if (!r.ok) throw new Error(`Upload failed (HTTP ${r.status})`);
    return r.json();
  },
  test: (target: 'chat' | 'embeddings' | 'search' | 'image') => j<{ ok: boolean; detail: string }>('/api/test', { method: 'POST', body: JSON.stringify({ target }) }),
};

export async function streamChat(body: unknown, onEvent: (e: ChatEvent) => void, signal: AbortSignal) {
  const r = await fetch(API + '/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
  if (!r.ok || !r.body) {
    let msg = `HTTP ${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch { /* ignore */ }
    throw new Error(msg);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i);
      buf = buf.slice(i + 2);
      if (chunk.startsWith('data:')) onEvent(JSON.parse(chunk.slice(5).trim()));
    }
  }
}

export function localIso() {
  const d = new Date(), p = (n: number) => String(n).padStart(2, '0'), o = -d.getTimezoneOffset();
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}${o >= 0 ? '+' : '-'}${p(Math.floor(Math.abs(o) / 60))}:${p(Math.abs(o) % 60)}`;
}
