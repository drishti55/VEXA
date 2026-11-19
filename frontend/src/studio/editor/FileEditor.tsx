import { useEffect, useRef } from 'react';
import Editor from '@monaco-editor/react';
import type { OnMount, BeforeMount } from '@monaco-editor/react';
import { Lock, AlertTriangle } from 'lucide-react';
import { useStudio, updateBuffer, saveFile, loadBuffer, setState, getState } from '../store';
import { languageFor } from '../util';

type MonacoEditor = Parameters<OnMount>[0];
type Monaco = Parameters<OnMount>[1];

const pendingReveal: Record<string, { line: number; query?: string; caseSensitive?: boolean }> = {};

export const defineThemes: BeforeMount = (monaco) => {
  monaco.editor.defineTheme('vexa-dark', {
    base: 'vs-dark', inherit: true, rules: [],
    colors: {
      'editor.background': '#1b1c1f', 'editorGutter.background': '#1b1c1f', 'minimap.background': '#1b1c1f',
      'editor.lineHighlightBackground': '#ffffff08', 'editorLineNumber.foreground': '#5a5b60',
      'editorLineNumber.activeForeground': '#c6c6c6', 'editorWidget.background': '#232428', 'editorWidget.border': '#3a3c42',
    },
  });
  monaco.editor.defineTheme('vexa-light', {
    base: 'vs', inherit: true, rules: [],
    colors: { 'editor.background': '#f8f8f9', 'editorGutter.background': '#f8f8f9', 'minimap.background': '#f8f8f9' },
  });
};

function revealIn(editor: MonacoEditor, monaco: Monaco, r: { line: number; query?: string; caseSensitive?: boolean }) {
  const model = editor.getModel();
  if (!model) return;
  const line = Math.min(Math.max(1, r.line), model.getLineCount());
  let range = new monaco.Range(line, 1, line, model.getLineMaxColumn(line));
  if (r.query) {
    const text = model.getLineContent(line);
    const idx = r.caseSensitive ? text.indexOf(r.query) : text.toLowerCase().indexOf(r.query.toLowerCase());
    if (idx >= 0) range = new monaco.Range(line, idx + 1, line, idx + 1 + r.query.length);
  }
  editor.revealRangeInCenter(range);
  editor.setSelection(range);
  editor.focus();
}

export function FileEditor({ path }: { path: string }) {
  const buffer = useStudio(s => s.buffers[path]);
  const theme = useStudio(s => s.theme);
  const prefs = useStudio(s => s.editorPrefs);
  const workspaceId = useStudio(s => s.workspaceId);
  // Agents write to the same files: while a run is active in this workspace the editor is read-only.
  const liveRun = useStudio(s => s.liveRunIds.map(id => s.runs[id]).find(r => r?.workspace_id === s.workspaceId && r.status === 'running'));
  const editorRef = useRef<MonacoEditor | null>(null);
  const monacoRef = useRef<Monaco | null>(null);
  const pathRef = useRef(path);
  pathRef.current = path;

  useEffect(() => {
    const h = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d.path !== path) return;
      if (editorRef.current && monacoRef.current && getState().buffers[path]?.loaded) revealIn(editorRef.current, monacoRef.current, d);
      else pendingReveal[path] = d;
    };
    document.addEventListener('vexa:reveal', h);
    return () => document.removeEventListener('vexa:reveal', h);
  }, [path]);

  useEffect(() => {
    if (buffer?.loaded && pendingReveal[path] && editorRef.current && monacoRef.current) {
      const r = pendingReveal[path];
      delete pendingReveal[path];
      setTimeout(() => editorRef.current && monacoRef.current && revealIn(editorRef.current, monacoRef.current, r), 0);
    }
  }, [buffer?.loaded, path]);

  const onMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;
    // one editor instance serves every file tab (models are swapped by `path`), so read the path from a ref
    editor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, () => saveFile(pathRef.current));
    editor.onDidChangeCursorPosition(e => setState({ cursor: { line: e.position.lineNumber, col: e.position.column } }));
    if (pendingReveal[path] && getState().buffers[path]?.loaded) {
      const r = pendingReveal[path];
      delete pendingReveal[path];
      revealIn(editor, monaco, r);
    }
  };

  if (!buffer || !buffer.loaded) return <div className="st-empty st-muted">Loading {path}…</div>;
  if (buffer.error) return <div className="st-empty"><p className="st-error">Cannot open {path}</p><p className="st-muted">{buffer.error}</p></div>;

  const readOnly = !!liveRun;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ height: 22, flex: 'none', display: 'flex', alignItems: 'center', gap: 4, padding: '0 12px', fontSize: 12, color: 'var(--text-muted)' }}>
        <span>{workspaceId}</span>
        {path.split('/').map((seg, i) => <span key={i}>› {seg}</span>)}
        {readOnly && <span className="st-pill run" style={{ marginLeft: 8 }}><Lock size={11} /> read-only while run {liveRun!.run_id.slice(0, 8)} is active in this workspace</span>}
      </div>
      {buffer.externalChange && (
        <div style={{ flex: 'none', display: 'flex', alignItems: 'center', gap: 8, padding: '6px 12px', background: 'color-mix(in srgb, var(--warn) 14%, transparent)', fontSize: 12 }}>
          <AlertTriangle size={14} style={{ color: 'var(--warn)' }} />
          <span style={{ flex: 1 }}>This file changed on disk (an agent run wrote it) while you had unsaved edits.</span>
          <button className="st-btn secondary" style={{ height: 22 }} onClick={() => {
            setState(s => ({ buffers: { ...s.buffers, [path]: { ...s.buffers[path], content: s.buffers[path].saved, loaded: false } } }));
            loadBuffer(path, true);
          }}>Reload from disk</button>
          <button className="st-btn secondary" style={{ height: 22 }} onClick={() => setState(s => ({ buffers: { ...s.buffers, [path]: { ...s.buffers[path], externalChange: false } } }))}>Keep my version</button>
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0 }} data-testid="monaco-host">
        <Editor
          path={path}
          defaultLanguage={languageFor(path)}
          language={languageFor(path)}
          value={buffer.content}
          theme={theme === 'light' ? 'vexa-light' : 'vexa-dark'}
          beforeMount={defineThemes}
          onMount={onMount}
          onChange={v => updateBuffer(path, v ?? '')}
          options={{
            readOnly, fontSize: prefs.fontSize, minimap: { enabled: prefs.minimap }, wordWrap: prefs.wordWrap ? 'on' : 'off', folding: true, lineNumbers: 'on',
            scrollBeyondLastLine: false, automaticLayout: true, renderWhitespace: 'selection', smoothScrolling: true,
            fontFamily: '"SF Mono", "JetBrains Mono", Menlo, Consolas, monospace', tabSize: 4, padding: { top: 4 },
          }}
        />
      </div>
    </div>
  );
}
