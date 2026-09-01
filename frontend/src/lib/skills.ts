import { authenticatedFetch } from "$lib/auth";

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
};
export class SkillsApiError extends Error { constructor(public status: number, message: string) { super(message); } }
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(url, init);
  if (!response.ok) throw new SkillsApiError(response.status, `Skills request failed (${response.status})`);
  return response.json() as Promise<T>;
}
const items = (value: SkillCatalogItem[] | { items?: SkillCatalogItem[] }) => Array.isArray(value) ? value : Array.isArray(value.items) ? value.items : [];
export async function listSkillCatalog(): Promise<SkillCatalogItem[]> { return items(await request<SkillCatalogItem[] | { items?: SkillCatalogItem[] }>("/api/skills/catalog")); }
export async function listEffectiveSkills(projectId: string): Promise<SkillCatalogItem[]> { return items(await request<SkillCatalogItem[] | { items?: SkillCatalogItem[] }>(`/api/projects/${encodeURIComponent(projectId)}/skills/effective`)); }
const mutate = (projectId: string, revisionId: string, action: "enable" | "disable" | "pin") => request<SkillCatalogItem>(`/api/projects/${encodeURIComponent(projectId)}/skills/${encodeURIComponent(revisionId)}/${action}`, { method: "POST" });
export const enableSkill = (projectId: string, revisionId: string, enabled: boolean) => mutate(projectId, revisionId, enabled ? "enable" : "disable");
export const pinSkill = (projectId: string, revisionId: string) => mutate(projectId, revisionId, "pin");
export const requestSkillInstall = (skillId: string) => request<{ candidate_id: string; status: string }>("/api/skills/install-request", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ skill_id: skillId }) });
