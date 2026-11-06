import type { ReactNode } from 'react';
const I = ({ children, s = 20 }: { children: ReactNode; s?: number }) => (
  <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{children}</svg>
);
export const Compose = () => <I><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4L16.5 3.5z" /></I>;
export const SidebarIcon = () => <I><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></I>;
export const Search = () => <I><circle cx="11" cy="11" r="7" /><path d="M20 20l-3.5-3.5" /></I>;
export const ArrowUp = () => <I s={18}><path d="M12 19V5" /><path d="M5 12l7-7 7 7" /></I>;
export const Stop = () => <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="4" y="4" width="16" height="16" rx="3" /></svg>;
export const Copy = () => <I s={16}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 012-2h9" /></I>;
export const Check = () => <I s={16}><path d="M5 12l5 5L20 7" /></I>;
export const Trash = () => <I s={16}><path d="M4 7h16" /><path d="M10 11v6M14 11v6" /><path d="M6 7l1 13h10l1-13" /><path d="M9 7V4h6v3" /></I>;
export const Pencil = () => <I s={16}><path d="M4 20l1-4L16.5 4.5a2.1 2.1 0 013 3L8 19l-4 1z" /></I>;
export const Gear = () => <I><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z" /></I>;
export const Chevron = () => <I s={14}><path d="M6 9l6 6 6-6" /></I>;
export const Close = () => <I s={18}><path d="M6 6l12 12M18 6L6 18" /></I>;
export const Globe = () => <I s={14}><circle cx="12" cy="12" r="9" /><path d="M3 12h18" /><path d="M12 3a14 14 0 010 18M12 3a14 14 0 000 18" /></I>;
export const Plus = () => <I><path d="M12 5v14M5 12h14" /></I>;
export const Clip = () => <I s={18}><path d="M21 11l-8.5 8.5a5 5 0 01-7-7L14 4a3.3 3.3 0 014.7 4.7L10.2 17.2a1.7 1.7 0 01-2.4-2.4L15 7.6" /></I>;
export const ImageIcon = () => <I s={18}><rect x="3" y="4" width="18" height="16" rx="3" /><circle cx="9" cy="10" r="1.6" /><path d="M21 16l-5-5-8 8" /></I>;
export const FileIcon = () => <I s={18}><path d="M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5z" /><path d="M14 3v5h5" /></I>;
export const Refresh = () => <I s={16}><path d="M20 11a8 8 0 10-2.3 5.7" /><path d="M20 4v7h-7" /></I>;
export const Download = () => <I s={16}><path d="M12 4v11" /><path d="M7 11l5 5 5-5" /><path d="M5 20h14" /></I>;
export const ArrowDown = () => <I s={18}><path d="M12 5v14" /><path d="M5 12l7 7 7-7" /></I>;
export const Export = () => <I><path d="M12 15V4" /><path d="M7 8l5-5 5 5" /><path d="M5 13v6a2 2 0 002 2h10a2 2 0 002-2v-6" /></I>;
