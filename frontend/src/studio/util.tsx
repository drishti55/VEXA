import {
  File, FileCode, FileJson, FileText, FileType, Image, Settings2, Database, Braces, Hash, Globe, Palette, TestTube2,
} from 'lucide-react';

const EXT_LANG: Record<string, string> = {
  py: 'python', ts: 'typescript', tsx: 'typescript', js: 'javascript', jsx: 'javascript', mjs: 'javascript', cjs: 'javascript',
  json: 'json', yml: 'yaml', yaml: 'yaml', md: 'markdown', markdown: 'markdown', html: 'html', htm: 'html',
  css: 'css', scss: 'scss', less: 'less', sql: 'sql', sh: 'shell', bash: 'shell', zsh: 'shell', toml: 'ini', ini: 'ini',
  cfg: 'ini', env: 'ini', xml: 'xml', svg: 'xml', go: 'go', rs: 'rust', java: 'java', c: 'c', h: 'c', cpp: 'cpp',
  rb: 'ruby', php: 'php', txt: 'plaintext', dockerfile: 'dockerfile',
};

export function languageFor(path: string): string {
  const name = path.split('/').pop()!.toLowerCase();
  if (name === 'dockerfile') return 'dockerfile';
  if (name.startsWith('.env')) return 'ini';
  const ext = name.includes('.') ? name.split('.').pop()! : '';
  return EXT_LANG[ext] ?? 'plaintext';
}

export function FileIcon({ path, size = 15 }: { path: string; size?: number }) {
  const name = path.split('/').pop()!.toLowerCase();
  const ext = name.includes('.') ? name.split('.').pop()! : '';
  const s = { width: size, height: size, flex: 'none' as const };
  if (name.startsWith('test_') || name.includes('.test.') || name.includes('.spec.')) return <TestTube2 style={{ ...s, color: '#c586c0' }} />;
  switch (ext) {
    case 'py': return <FileCode style={{ ...s, color: '#4b8bbe' }} />;
    case 'ts': case 'tsx': return <FileCode style={{ ...s, color: '#3178c6' }} />;
    case 'js': case 'jsx': case 'mjs': case 'cjs': return <FileCode style={{ ...s, color: '#d7ba3d' }} />;
    case 'json': return <FileJson style={{ ...s, color: '#cbcb41' }} />;
    case 'md': case 'markdown': return <FileText style={{ ...s, color: '#519aba' }} />;
    case 'html': case 'htm': return <Globe style={{ ...s, color: '#e44d26' }} />;
    case 'css': case 'scss': case 'less': return <Palette style={{ ...s, color: '#42a5f5' }} />;
    case 'yml': case 'yaml': case 'toml': case 'ini': case 'cfg': return <Settings2 style={{ ...s, color: '#a074c4' }} />;
    case 'sql': case 'sqlite3': case 'db': return <Database style={{ ...s, color: '#dad8d8' }} />;
    case 'png': case 'jpg': case 'jpeg': case 'gif': case 'svg': case 'webp': return <Image style={{ ...s, color: '#a074c4' }} />;
    case 'sh': case 'bash': case 'zsh': return <Hash style={{ ...s, color: '#89e051' }} />;
    case 'txt': return <FileType style={{ ...s, color: 'var(--text-muted)' }} />;
    case 'lock': return <Braces style={{ ...s, color: 'var(--text-muted)' }} />;
    default: return <File style={{ ...s, color: 'var(--text-muted)' }} />;
  }
}

export function fmtTime(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return isNaN(+d) ? '—' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

export function fmtMs(ms?: number | null): string {
  if (ms == null || !isFinite(ms)) return '—';
  if (ms < 1) return '<1 ms';
  if (ms < 1000) return `${Math.round(ms)} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;
}

export function timeAgo(iso?: string | null): string {
  if (!iso) return '';
  const s = (Date.now() - +new Date(iso)) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 14) return `${Math.floor(s / 86400)} days ago`;
  return `${Math.floor(s / 86400 / 7)} wks ago`;
}

/** Runs from GET /agent-runs are either full (live) or a registry summary ({result: {summary}}). */
export function runRequirement(r: { run_id: string; result?: any }): string {
  return r.result?.requirement ?? r.result?.summary?.requirement ?? r.run_id;
}
export function runStartedAt(r: { result?: any }): string | null {
  return r.result?.started_at ?? r.result?.summary?.started_at ?? null;
}

export const STATUS_COLOR: Record<string, string> = {
  running: 'var(--run)', success: 'var(--ok)', completed: 'var(--ok)', partial: 'var(--warn)', failed: 'var(--err)',
  interrupted: 'var(--warn)', cancelled: 'var(--text-faint)', idle: 'var(--text-faint)', queued: 'var(--text-faint)',
  retrying: 'var(--warn)', blocked: 'var(--err)', waiting: 'var(--text-muted)', reviewing: 'var(--info)',
};

export function StatusDot({ status, pulse }: { status: string; pulse?: boolean }) {
  return <span className={`dot${pulse ? ' pulse' : ''}`} style={{ background: STATUS_COLOR[status] ?? 'var(--text-faint)' }} />;
}
