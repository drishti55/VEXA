// Model + API key chosen in the Studio for real runs.
//
// The key lives only in this browser: sessionStorage by default (cleared when the tab closes),
// localStorage only if the user ticks "remember on this device". It is sent to the backend
// with each run / model test as llm_api_key and is never stored by the backend.
import { useSyncExternalStore } from 'react';

export interface LlmCredentials { model: string; apiKey: string; remember: boolean }

const KEY = 'vexa-studio:llm:v1';
const EMPTY: LlmCredentials = { model: '', apiKey: '', remember: false };
const listeners = new Set<() => void>();

function storage(kind: 'local' | 'session'): Storage | null {
  try { return kind === 'local' ? window.localStorage : window.sessionStorage; } catch { return null; }
}

function read(): LlmCredentials {
  for (const kind of ['session', 'local'] as const) {
    try {
      const raw = storage(kind)?.getItem(KEY);
      if (raw) return { ...EMPTY, ...JSON.parse(raw) };
    } catch { /* unreadable: ignore */ }
  }
  return EMPTY;
}

let current = read();

export function getLlmCredentials(): LlmCredentials { return current; }

export function setLlmCredentials(next: Partial<LlmCredentials>): void {
  current = { ...current, ...next };
  const raw = JSON.stringify(current);
  try { storage('session')?.setItem(KEY, raw); } catch { /* ignore */ }
  try {
    if (current.remember) storage('local')?.setItem(KEY, raw);
    else storage('local')?.removeItem(KEY);
  } catch { /* ignore */ }
  listeners.forEach(l => l());
}

export function clearLlmCredentials(): void {
  try { storage('session')?.removeItem(KEY); storage('local')?.removeItem(KEY); } catch { /* ignore */ }
  current = EMPTY;
  listeners.forEach(l => l());
}

export function useLlmCredentials(): LlmCredentials {
  return useSyncExternalStore(cb => { listeners.add(cb); return () => listeners.delete(cb); }, () => current);
}

/** Model presets that work with LiteLLM; the default is picked from the key's prefix when no model is set. */
export const MODEL_PRESETS = [
  { model: 'groq/openai/gpt-oss-20b', label: 'Groq · gpt-oss-20b' },
  { model: 'groq/openai/gpt-oss-120b', label: 'Groq · gpt-oss-120b' },
  { model: 'gemini/gemini-2.0-flash', label: 'Google · Gemini 2.0 Flash' },
  { model: 'gpt-4o-mini', label: 'OpenAI · gpt-4o-mini' },
];

export function modelForKey(apiKey: string, model: string): string {
  if (model.trim()) return model.trim();
  if (apiKey.startsWith('gsk_')) return 'groq/openai/gpt-oss-20b';
  if (apiKey.startsWith('AIza')) return 'gemini/gemini-2.0-flash';
  if (apiKey.startsWith('sk-')) return 'gpt-4o-mini';
  return '';
}
