const STORAGE_KEY = 'archon.active-project';
export const DEFAULT_PROJECT_ID = 'default';

export function readProjectScope(): string {
  if (typeof localStorage === 'undefined') return DEFAULT_PROJECT_ID;
  return localStorage.getItem(STORAGE_KEY)?.trim() || DEFAULT_PROJECT_ID;
}

export function writeProjectScope(projectId: string): void {
  if (typeof localStorage === 'undefined') return;
  const normalized = projectId.trim() || DEFAULT_PROJECT_ID;
  localStorage.setItem(STORAGE_KEY, normalized);
  window.dispatchEvent(new CustomEvent('archon:project-scope', { detail: normalized }));
}
