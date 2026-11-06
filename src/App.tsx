import { useCallback, useEffect, useRef, useState } from 'react';
import { api, deepMerge, localIso, streamChat } from './api';
import type { Conv, Msg, Settings } from './api';
import Sidebar from './Sidebar';
import ChatView from './ChatView';
import type { SendOpts } from './ChatView';
import SettingsModal from './SettingsModal';

export default function App() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [convs, setConvs] = useState<Conv[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [status, setStatus] = useState('');
  const [sidebar, setSidebar] = useState(true);
  const [modal, setModal] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRef = useRef<string | null>(null);
  const pending = useRef<any>({});
  const timer = useRef<number>();
  activeRef.current = active;

  const refreshConvs = useCallback(() => { api.convs().then(setConvs).catch(() => {}); }, []);

  useEffect(() => {
    let tries = 0;
    const boot = () => api.settings().then((s) => { setSettings(s); refreshConvs(); }).catch(() => { if (tries++ < 40) setTimeout(boot, 400); });
    boot();
  }, [refreshConvs]);

  useEffect(() => {
    if (!settings) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const apply = () => { document.documentElement.dataset.theme = settings.theme === 'system' ? (mq.matches ? 'dark' : 'light') : settings.theme; };
    apply();
    mq.addEventListener('change', apply);
    window.zen?.setTheme(settings.theme);
    return () => mq.removeEventListener('change', apply);
  }, [settings?.theme]);

  const patch = useCallback((p: any) => {
    setSettings((s) => (s ? deepMerge(s, p) : s));
    pending.current = deepMerge(pending.current, p);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => { api.putSettings(pending.current).catch(() => {}); pending.current = {}; }, 500);
  }, []);

  const newChat = useCallback(() => { abortRef.current?.abort(); setActive(null); setMsgs([]); }, []);
  const select = async (id: string) => {
    abortRef.current?.abort();
    setActive(id);
    setMsgs(await api.messages(id).catch(() => []));
  };

  const run = async (text: string, o: SendOpts = {}) => {
    if (streaming || !settings) return;
    const ac = new AbortController();
    abortRef.current = ac;
    setStreaming(true);
    const t = Date.now();
    const user: Msg = { id: 'tmp-u' + t, role: 'user', content: text, sources: [], attachments: o.attachments ?? [] };
    const bot: Msg = { id: 'tmp-a' + t, role: 'assistant', content: '', sources: [], files: [] };
    setMsgs((ms) => {
      if (o.regenerate) { const c = [...ms]; if (c.length && c[c.length - 1].role === 'assistant') c.pop(); return [...c, bot]; }
      if (o.truncateFrom) { const i = ms.findIndex((m) => m.id === o.truncateFrom); return [...(i >= 0 ? ms.slice(0, i) : ms), user, bot]; }
      return [...ms, user, bot];
    });
    const upd = (f: (m: Msg) => Msg) => setMsgs((ms) => ms.map((m, i) => (i === ms.length - 1 ? f(m) : m)));
    let cid = active;
    try {
      await streamChat(
        {
          conversation_id: active, message: text, model: settings.chat.model,
          client: { now: localIso(), tz: Intl.DateTimeFormat().resolvedOptions().timeZone, locale: navigator.language },
          attachments: (o.attachments ?? []).map((a) => a.id), mode: o.mode ?? 'chat', search: !!o.search,
          regenerate: !!o.regenerate, truncate_from: o.truncateFrom ?? null,
        },
        (ev) => {
          switch (ev.type) {
            case 'meta': cid = ev.conversation_id; setActive(ev.conversation_id); break;
            case 'status': setStatus(ev.text); break;
            case 'sources': upd((m) => ({ ...m, sources: ev.items })); break;
            case 'token': upd((m) => ({ ...m, content: m.content + ev.text })); break;
            case 'file_start': upd((m) => ({ ...m, pending: ev.name || (ev.kind === 'image' ? 'image' : 'file') })); break;
            case 'file': upd((m) => ({ ...m, pending: undefined, files: [...(m.files ?? []), ev.file] })); break;
            case 'file_error': upd((m) => ({ ...m, pending: undefined, error: ev.message })); break;
            case 'title': refreshConvs(); break;
            case 'error': upd((m) => ({ ...m, error: ev.message })); break;
          }
        },
        ac.signal,
      );
    } catch (e: any) {
      if (e.name !== 'AbortError') upd((m) => ({ ...m, error: e.message || String(e) }));
    } finally {
      setStreaming(false); setStatus(''); abortRef.current = null; refreshConvs();
      upd((m) => ({ ...m, pending: undefined }));
      if (cid) {
        const id = cid;
        api.messages(id).then((server) => {
          if (activeRef.current !== id) return;
          setMsgs((ms) => ms.map((m, i) => (server[i] && server[i].role === m.role ? { ...m, id: server[i].id, attachments: server[i].attachments, files: m.files?.length ? m.files : server[i].files } : m)));
        }).catch(() => {});
      }
    }
  };

  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.shiftKey && e.key.toLowerCase() === 'o') { e.preventDefault(); newChat(); }
      else if (mod && e.key.toLowerCase() === 'b') { e.preventDefault(); setSidebar((s) => !s); }
      else if (mod && e.key === ',') { e.preventDefault(); setModal('General'); }
      else if (e.key === 'Escape' && abortRef.current) abortRef.current.abort();
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [newChat]);

  if (!settings) return <div className="boot"><span className="spin big" /> Starting Zen…</div>;

  return (
    <div className="app">
      <Sidebar
        convs={convs} active={active} open={sidebar} name={settings.profile.name}
        onSelect={select} onNew={newChat} onToggle={() => setSidebar(false)} onSettings={() => setModal('General')}
        onDelete={(id) => { api.del(id).then(() => { if (id === active) newChat(); refreshConvs(); }); }}
        onRename={(id, title) => { api.rename(id, title).then(refreshConvs); }}
      />
      <ChatView
        msgs={msgs} streaming={streaming} status={status} settings={settings} sidebarOpen={sidebar} activeId={active}
        onSend={run} onStop={() => abortRef.current?.abort()} onModel={(id) => patch({ chat: { model: id } })}
        onRegenerate={() => run('', { regenerate: true })}
        onEdit={(id, text) => run(text, { truncateFrom: id, attachments: msgs.find((m) => m.id === id)?.attachments })}
        onSettings={(tab) => setModal(tab || 'General')} onToggleSidebar={() => setSidebar(true)} onNew={newChat}
      />
      {modal && <SettingsModal s={settings} patch={patch} tab={modal} onClose={() => setModal(null)} />}
    </div>
  );
}
