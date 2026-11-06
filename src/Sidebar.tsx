import { useMemo, useState } from 'react';
import type { Conv } from './api';
import { Compose, Pencil, Search, SidebarIcon, Trash } from './icons';

interface Props {
  convs: Conv[]; active: string | null; open: boolean; name: string;
  onSelect: (id: string) => void; onNew: () => void; onDelete: (id: string) => void;
  onRename: (id: string, t: string) => void; onSettings: () => void; onToggle: () => void;
}

function group(convs: Conv[]) {
  const now = new Date(); const sod = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  const buckets: [string, Conv[]][] = [['Today', []], ['Yesterday', []], ['Previous 7 days', []], ['Previous 30 days', []], ['Older', []]];
  for (const c of convs) {
    const d = (sod - c.updated) / 86400;
    buckets[c.updated >= sod ? 0 : d <= 1 ? 1 : d <= 7 ? 2 : d <= 30 ? 3 : 4][1].push(c);
  }
  return buckets.filter(([, l]) => l.length);
}

export default function Sidebar(p: Props) {
  const [q, setQ] = useState(''); const [searching, setSearching] = useState(false);
  const [editing, setEditing] = useState<string | null>(null); const [draft, setDraft] = useState('');
  const groups = useMemo(() => group(p.convs.filter((c) => c.title.toLowerCase().includes(q.toLowerCase()))), [p.convs, q]);
  const commit = () => { if (editing && draft.trim()) p.onRename(editing, draft.trim()); setEditing(null); };
  return (
    <aside className={'sidebar' + (p.open ? '' : ' closed')}>
      <div className="sb-inner">
        <div className="sb-top">
          <div className="logo">Z</div>
          <button className="icon-btn" title="Close sidebar" onClick={p.onToggle}><SidebarIcon /></button>
        </div>
        <button className="sb-item" onClick={p.onNew}><Compose /> New chat</button>
        <button className="sb-item" onClick={() => { setSearching(!searching); setQ(''); }}><Search /> Search chats</button>
        {searching && <input className="sb-search" autoFocus placeholder="Search chats" value={q} onChange={(e) => setQ(e.target.value)} />}
        <div className="sb-list">
          {groups.map(([label, list]) => (
            <div key={label}>
              <div className="sb-label">{label}</div>
              {list.map((c) => (
                <div key={c.id} className={'conv' + (c.id === p.active ? ' active' : '')} onClick={() => p.onSelect(c.id)}>
                  {editing === c.id ? (
                    <input className="rename" autoFocus value={draft} onClick={(e) => e.stopPropagation()} onChange={(e) => setDraft(e.target.value)}
                      onBlur={commit} onKeyDown={(e) => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') setEditing(null); }} />
                  ) : (
                    <>
                      <span className="conv-title">{c.title}</span>
                      <span className="conv-actions">
                        <button title="Rename" onClick={(e) => { e.stopPropagation(); setEditing(c.id); setDraft(c.title); }}><Pencil /></button>
                        <button title="Delete" onClick={(e) => { e.stopPropagation(); if (confirm('Delete this chat?')) p.onDelete(c.id); }}><Trash /></button>
                      </span>
                    </>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
        <button className="profile" onClick={p.onSettings}>
          <span className="avatar">{(p.name || 'Z')[0].toUpperCase()}</span>
          <span className="pname">{p.name || 'Settings'}</span>
        </button>
      </div>
    </aside>
  );
}
