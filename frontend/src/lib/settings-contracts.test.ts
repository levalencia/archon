import { beforeEach, describe, expect, it, vi } from 'vitest';
vi.mock('$lib/auth', () => ({ authenticatedFetch: vi.fn() }));
import { authenticatedFetch } from '$lib/auth';
import { listProjectInstructions, scanProjectWorkspace } from './project-instructions';
import { enableSkill, listSkillCatalog, requestSkillInstall } from './skills';
import { disableCapability, listEffectiveCapabilities, pinCapability } from './capabilities';
const api=vi.mocked(authenticatedFetch);
beforeEach(()=>api.mockReset());
describe('project settings typed clients',()=>{
 it('encodes project instruction scope and normalizes item envelopes',async()=>{api.mockResolvedValueOnce(new Response(JSON.stringify({items:[{id:'i1',relative_path:'AGENTS.md',scope_path:'.',revision:'7',content_hash:'abc',trust_state:'trusted',byte_count:12}]}),{status:200}));expect((await listProjectInstructions('team/a'))[0].relative_path).toBe('AGENTS.md');expect(api.mock.calls[0][0]).toBe('/api/projects/team%2Fa/instructions');api.mockResolvedValueOnce(new Response('{}',{status:200}));await scanProjectWorkspace('team/a');expect(api.mock.calls[1][0]).toBe('/api/projects/team%2Fa/workspace/scan')});
 it('uses catalog and governed skill mutations without raw import',async()=>{api.mockImplementation(async()=>new Response(JSON.stringify({items:[]}),{status:200}));await listSkillCatalog();await enableSkill('project/a','skill/1',true);await requestSkillInstall('skill/1');expect(api.mock.calls.map(x=>x[0])).toEqual(['/api/skills/catalog','/api/projects/project%2Fa/skills/skill%2F1/enable','/api/skills/install-request']);expect(JSON.parse(String(api.mock.calls[2][1]?.body))).toEqual({skill_id:'skill/1'})});
 it('loads and mutates capability inventory without execution calls',async()=>{api.mockImplementation(async()=>new Response(JSON.stringify({items:[]}),{status:200}));await listEffectiveCapabilities('p/a');await pinCapability('p/a','tool/x');await disableCapability('p/a','tool/x');expect(api.mock.calls.map(x=>x[0])).toEqual(['/api/projects/p%2Fa/capabilities/effective','/api/projects/p%2Fa/capabilities/tool%2Fx/pin','/api/projects/p%2Fa/capabilities/tool%2Fx/disable'])});
});
