import { RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';
import { API_BASE_URL, VexaApi } from './api/client';

interface WebPreviewProps {
  workspaceId: string;
}

export function WebPreview({ workspaceId }: WebPreviewProps) {
  const [key, setKey] = useState(0);
  // Only web projects can be previewed: check for index.html instead of loading a 404 page.
  const checkKey = `${workspaceId}:${key}`;
  const [check, setCheck] = useState<{ key: string; has: boolean } | null>(null);
  const hasIndex = check?.key === checkKey ? check.has : null;  // null while this workspace is being checked
  useEffect(() => {
    if (!workspaceId) return;
    VexaApi.listFiles(workspaceId)
      .then(r => setCheck({ key: checkKey, has: Array.isArray(r?.data) && r.data.some((f: any) => !f.is_dir && f.path === 'index.html') }))
      .catch(() => setCheck({ key: checkKey, has: false }));
  }, [workspaceId, checkKey]);

  // The backend serves the workspace root at this endpoint
  // By default, it loads index.html
  const previewUrl = `${API_BASE_URL}/workspaces/${encodeURIComponent(workspaceId)}/serve/`;

  const handleRefresh = () => {
    setKey(k => k + 1);
  };

  if (!workspaceId) {
    return (
      <div className="flex-1 flex items-center justify-center text-vexa-muted">
        Select a workspace to preview.
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-vexa-panel">
      {/* Browser Chrome Bar */}
      <div className="flex items-center space-x-2 bg-vexa-bg p-2 border-b border-vexa-border">
        <button 
          onClick={handleRefresh}
          className="p-1 hover:bg-vexa-panel rounded text-vexa-muted hover:text-white transition-colors"
          title="Refresh Preview"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
        <div className="flex-1 bg-black/40 rounded px-3 py-1 font-mono text-xs text-vexa-muted truncate border border-vexa-border">
          {previewUrl}
        </div>
      </div>
      
      {/* Iframe */}
      {hasIndex === false ? (
        <div data-testid="preview-unavailable" className="flex-1 flex items-center justify-center text-vexa-muted text-sm p-6 text-center">
          No index.html at the workspace root — this project has no web page to preview. Use the Code tab to inspect files.
        </div>
      ) : hasIndex === null ? (
        <div className="flex-1 flex items-center justify-center text-vexa-muted text-sm">Checking for a web page…</div>
      ) : (
      <div className="flex-1 bg-white">
        <iframe
          key={key}
          src={previewUrl}
          className="w-full h-full border-0"
          title="Web Preview"
          // No allow-same-origin: generated code runs in an opaque origin and
          // cannot call the VEXA API (the server also sends a CSP sandbox header).
          sandbox="allow-scripts allow-forms allow-modals"
        />
      </div>
      )}
    </div>
  );
}
