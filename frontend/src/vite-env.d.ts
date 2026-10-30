/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_VEXA_API_URL?: string;
  readonly VITE_VEXA_API_TOKEN?: string;
  readonly VITE_DEFAULT_VERIFIER?: string;        // 'adk_a2a' (default) | 'crewai'
  readonly VITE_DEFAULT_TOOL_TRANSPORT?: string;  // 'mcp' (default) | 'direct'
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
