import { useState, useEffect } from 'react';
import Editor from '@monaco-editor/react';
import { VexaApi } from './api/client';
import { FileCode, Folder, Loader2 } from 'lucide-react';

interface CodeEditorProps {
  workspaceId: string;
}

export function CodeEditor({ workspaceId }: CodeEditorProps) {
  const [files, setFiles] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!workspaceId) return;
    loadFiles();
  }, [workspaceId]);

  const loadFiles = async () => {
    try {
      const result = await VexaApi.listFiles(workspaceId);
      if (result && result.data && Array.isArray(result.data)) {
        // Filter out directories and extract just the path string
        const filePaths = result.data.filter((f: any) => !f.is_dir).map((f: any) => f.path);
        setFiles(filePaths);
      } else {
        setFiles([]);
      }
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleSelectFile = async (path: string) => {
    setSelectedFile(path);
    setIsLoading(true);
    setError(null);
    try {
      const result = await VexaApi.readFile(workspaceId, path);
      setFileContent(result.data?.content || '');
    } catch (err: any) {
      setError(err.message);
      setFileContent('');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex h-full bg-vexa-bg text-white">
      {/* Sidebar */}
      <div className="w-64 border-r border-vexa-border flex flex-col">
        <div className="p-3 border-b border-vexa-border flex justify-between items-center">
          <span className="text-xs font-bold uppercase tracking-wider text-vexa-muted flex items-center">
            <Folder className="w-4 h-4 mr-2" /> Files
          </span>
          <button onClick={loadFiles} className="text-vexa-accent text-xs hover:underline">Refresh</button>
        </div>
        <div className="flex-1 overflow-y-auto p-2">
          {files.map(f => (
            <div 
              key={f}
              className={`text-xs font-mono p-2 cursor-pointer flex items-center rounded ${selectedFile === f ? 'bg-vexa-accent/20 text-vexa-accent' : 'hover:bg-vexa-panel text-gray-300'}`}
              onClick={() => handleSelectFile(f)}
            >
              <FileCode className="w-3 h-3 mr-2" /> {f}
            </div>
          ))}
          {files.length === 0 && <div className="text-xs text-vexa-muted p-2">No files found.</div>}
        </div>
      </div>

      {/* Editor Pane */}
      <div className="flex-1 flex flex-col relative">
        {isLoading && (
          <div className="absolute inset-0 z-10 bg-vexa-bg/80 flex items-center justify-center">
            <Loader2 className="w-8 h-8 animate-spin text-vexa-accent" />
          </div>
        )}
        {error && (
          <div className="absolute inset-x-0 top-0 z-10 bg-vexa-error/20 border-b border-vexa-error text-vexa-error p-2 text-xs">
            {error}
          </div>
        )}
        
        {selectedFile ? (
          <div className="flex-1">
            <Editor
              height="100%"
              theme="vs-dark"
              path={selectedFile}
              value={fileContent}
              options={{ readOnly: true, minimap: { enabled: false } }}
            />
          </div>
        ) : (
          <div className="flex-1 flex items-center justify-center text-vexa-muted text-sm">
            Select a file from the sidebar to view its contents.
          </div>
        )}
      </div>
    </div>
  );
}
