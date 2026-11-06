import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';
import { openExternal } from './api';
import { Check, Copy } from './icons';

function Code({ className, children }: { className?: string; children?: React.ReactNode }) {
  const [done, setDone] = useState(false);
  const lang = /language-([\w-]+)/.exec(className || '')?.[1];
  const text = (function flat(n: any): string { return typeof n === 'string' ? n : Array.isArray(n) ? n.map(flat).join('') : n?.props ? flat(n.props.children) : ''; })(children).replace(/\n$/, '');
  if (!lang && !text.includes('\n')) return <code className="inline">{children}</code>;
  return (
    <div className="codeblock">
      <div className="codehead">
        <span>{lang || 'code'}</span>
        <button onClick={() => { navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }}>
          {done ? <Check /> : <Copy />} {done ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre><code className={className}>{children}</code></pre>
    </div>
  );
}

export default function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          code: Code as any,
          pre: ({ children }: any) => <>{children}</>,
          a: ({ href, children }: any) => <a href={href} onClick={(e) => { e.preventDefault(); if (href) openExternal(href); }}>{children}</a>,
          table: ({ children }: any) => <div className="tablewrap"><table>{children}</table></div>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}
