import { authenticatedFetch } from '$lib/auth';

export type SkillCatalogItem = {
  id: string;
  name: string;
  description: string;
  kind: string;
  source: string;
  version: string;
  trust_state: string;
  enabled: boolean;
  pinned: boolean;
  risk_classes: string[];
  /** Forward-compatible: required for binding once the catalog exposes it. */
  revision_id?: string;
  source_revision?: string;
  source_path?: string;
};
export type SkillInstallRequest = { repository: string; revision: string; path?: string };
export class SkillsApiError extends Error {
  constructor(public status: number, public code: string) {
    super(status === 401 ? 'Sign in required' : `Skills request failed (${code})`);
    this.name = 'SkillsApiError';
  }
}
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(url, init);
  if (!response.ok) {
    let code = `http_${response.status}`;
    try { const value = await response.json(); code = value?.detail?.code ?? value?.code ?? code; } catch { /* non-JSON */ }
    throw new SkillsApiError(response.status, code);
  }
  return response.json() as Promise<T>;
}
const items = (value: SkillCatalogItem[] | { items?: SkillCatalogItem[] }) => Array.isArray(value) ? value : Array.isArray(value.items) ? value.items : [];
export async function listSkillCatalog(projectId?: string): Promise<SkillCatalogItem[]> {
  const suffix = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return items(await request<SkillCatalogItem[]>(`/api/skills/catalog${suffix}`));
}
export async function listEffectiveSkills(projectId: string): Promise<SkillCatalogItem[]> {
  const result = await request<{ items?: SkillCatalogItem[] }>(`/api/skills/projects/${encodeURIComponent(projectId)}/effective`);
  return Array.isArray(result.items) ? result.items : [];
}
export const bindSkill = (projectId: string, packageId: string, revisionId: string, enabled: boolean, pinned: boolean) =>
  request<SkillCatalogItem>(`/api/skills/projects/${encodeURIComponent(projectId)}/${encodeURIComponent(packageId)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ revision_id: revisionId, enabled, pinned }),
  });
export const requestSkillInstall = (input: SkillInstallRequest) => request<SkillCatalogItem>('/api/skills/install-requests', {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ repository: input.repository, revision: input.revision, path: input.path ?? 'SKILL.md' }),
});
