/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_VEXA_API_URL?: string;
  readonly VITE_VEXA_API_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
