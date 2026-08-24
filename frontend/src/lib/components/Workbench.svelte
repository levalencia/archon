<script lang="ts">
 import { onMount } from 'svelte'; import { goto } from '$app/navigation'; import { page } from '$app/state';
 import Sidebar from '$lib/components/Sidebar.svelte'; import ChatMessages from '$lib/components/ChatMessages.svelte'; import ChatInput from '$lib/components/ChatInput.svelte'; import Inspector from '$lib/components/Inspector.svelte'; import ArtifactPanel from '$lib/components/ArtifactPanel.svelte';
 import { SSEParser, type SSEEvent } from '$lib/sse'; import type { Artifact, ContextStats, InspectorTab, LogEntry, Message, RunStats } from '$lib/types';
 import { authenticatedFetch } from '$lib/auth';
 let { initialId = '' }: { initialId?: string } = $props();
 let messages: Message[] = $state([]);
 let artifacts: Artifact[] = $state([]);
 let logs: LogEntry[] = $state([]);
 let context: ContextStats | undefined = $state();
 let currentId = $state('');
 let loading = $state(false);
 let error = $state('');
 let artifactOpen = $state(false);
 let model = $state('Connecting…');
 let provider = $state('');
 let hydrated = $state(false);
 let activeTab: InspectorTab = $state('run');
 let stats: RunStats = $state({ latency: '—', tokens: '—', tools: 0, iterations: 0 });
 let controller: AbortController | null = null;
 let logController: AbortController | null = null;
 let sidebarElement: HTMLElement;
 let sidebarScrim: HTMLButtonElement;
 let inspectorElement: HTMLElement;
 let inspectorScrim: HTMLButtonElement;
 const prompts = ['Investigate the latest failed run', 'Evaluate an answer for groundedness', 'Create a reliability test plan'];
 onMount(() => { hydrated = true; loadHealth(); connectLogs(); if (initialId) loadConversation(initialId, false); return () => { controller?.abort(); logController?.abort(); }; });
 async function loadHealth() { try { const r = await fetch('/api/admin/health'); if (!r.ok) throw new Error(); const d = await r.json(); model = d.llm_model || 'Configured model'; provider = d.llm_provider || ''; } catch { model = 'Backend unavailable'; provider = ''; } }
 async function connectLogs() { logController = new AbortController(); try { const r = await authenticatedFetch('/api/logs/stream', { signal: logController.signal }); if (!r.ok || !r.body) return; const reader=r.body.getReader(), decoder=new TextDecoder(), parser=new SSEParser(); while(true){const {done,value}=await reader.read();for(const event of parser.push(done?'':decoder.decode(value,{stream:true}),done)){if(event.event==='message'){try{logs=[...logs.slice(-249),JSON.parse(event.data)];}catch{}}}if(done)break;} } catch(e) { if((e as Error).name!=='AbortError') console.warn('Log stream unavailable'); } }
 function reset() { controller?.abort(); currentId=''; messages=[]; artifacts=[]; context=undefined; stats={latency:'—',tokens:'—',tools:0,iterations:0}; error=''; setOverlay(sidebarElement, sidebarScrim, false); goto('/'); }
 async function loadConversation(id: string, route=true) { controller?.abort(); currentId=id; setOverlay(sidebarElement, sidebarScrim, false); error=''; loading=true; if(route) goto(`/chat/${id}`); try { const r=await authenticatedFetch(`/api/chat/history/${id}`); if(!r.ok) throw new Error(`Could not load conversation (${r.status})`); const d=await r.json(); messages=(d.messages||[]).map((m:any,i:number)=>({id:i,role:m.role,content:m.content,timestamp:''})); } catch(e) { error=e instanceof Error?e.message:'Could not load conversation'; messages=[]; } finally { loading=false; } }
 function apply(event:SSEEvent, am:Message) { const payload=event.data; if(event.event==='token') am.content+=payload; else if(event.event==='thinking') am.thinking_steps=[...(am.thinking_steps||[]),{type:'thinking',detail:payload}]; else if(event.event==='skill') { try{am.skills_used=[...(am.skills_used||[]),JSON.parse(payload)];}catch{} } else if(event.event==='tool_call'){try{am.tool_calls=[...(am.tool_calls||[]),JSON.parse(payload)];}catch{}} else if(event.event==='artifact'){try{const a=JSON.parse(payload);am.artifacts=[...(am.artifacts||[]),a];artifacts=[...artifacts,a];}catch{}} else if(event.event==='context'){try{context=JSON.parse(payload);am.context_stats=context;}catch{}} else if(event.event==='done'){try{const d=JSON.parse(payload);am.iterations=d.iterations;stats={iterations:d.iterations||0,tools:d.tools_used||0,latency:d.elapsed_ms!=null?`${d.elapsed_ms}ms`:'—',tokens:d.tokens_used!=null?String(d.tokens_used):'—'};}catch{}} messages=[...messages.slice(0,-1),{...am}]; }
 async function send(text:string,image?:string){ if(loading)return; error=''; loading=true; controller=new AbortController(); messages=[...messages,{id:Date.now(),role:'user',content:text,timestamp:new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}]; try { if(!currentId){const r=await authenticatedFetch('/api/conversations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:text.slice(0,50)}),signal:controller.signal});if(!r.ok)throw new Error(`Could not create conversation (${r.status})`);currentId=(await r.json()).id;goto(`/chat/${currentId}`,{replaceState:true});} const am:Message={id:Date.now()+1,role:'assistant',content:'',timestamp:new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}),thinking_steps:[],tool_calls:[],skills_used:[],artifacts:[]};messages=[...messages,am];const r=await authenticatedFetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:text,conversation_id:currentId,image:image||''}),signal:controller.signal});if(!r.ok||!r.body)throw new Error(`Run failed (${r.status})`);const reader=r.body.getReader(),decoder=new TextDecoder(),parser=new SSEParser();while(true){const {done,value}=await reader.read();for(const event of parser.push(done?'':decoder.decode(value,{stream:true}),done))apply(event,am);if(done)break;}}catch(e){if((e as Error).name!=='AbortError')error=e instanceof Error?e.message:'The run failed';}finally{loading=false;controller=null;} }
 function cancel(){controller?.abort();loading=false;}
 function setOverlay(element: HTMLElement, scrim: HTMLButtonElement, open: boolean) {
   element.classList.toggle('open', open);
   element.setAttribute('data-open', String(open));
   element.toggleAttribute('inert', !open);
   scrim.classList.toggle('open', open);
   scrim.tabIndex = open ? 0 : -1;
 }




</script>
<div class="workbench">
 <button bind:this={sidebarScrim} class="scrim" aria-label="Close conversations" tabindex="-1" onclick={() => setOverlay(sidebarElement, sidebarScrim, false)}></button>
 <aside bind:this={sidebarElement} data-open="false" inert class="sidebar"><Sidebar activeId={currentId} onSelect={loadConversation} onNew={reset} onClose={() => setOverlay(sidebarElement, sidebarScrim, false)}/></aside>
 <main class="main"><header class="topbar"><button class="icon-button nav-toggle" aria-label="Open conversations" disabled={!hydrated} onclick={() => setOverlay(sidebarElement, sidebarScrim, true)}><svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button><div class="title"><p>Agent Reliability Workbench</p><span><i class:offline={model==='Backend unavailable'}></i>{model} {provider ? `· ${provider}` : ''}</span></div><button class="mobile-inspector" disabled={!hydrated} onclick={() => setOverlay(inspectorElement, inspectorScrim, true)}>Inspect run</button></header>
 {#if error}<div class="error-banner" role="alert"><span>{error}</span><button onclick={()=>error=''}>Dismiss</button></div>{/if}
 {#if messages.length===0}<section class="empty-state"><div class="hero-mark">A</div><p class="eyebrow">Agent operations</p><h1>Make every answer<br><span>production-ready.</span></h1><p>Run prompts, inspect evidence, and diagnose reliability signals in one focused workspace.</p><div class="starter"><span>Start with a workflow</span>{#each prompts as prompt}<button onclick={()=>send(prompt)}>{prompt}<b>→</b></button>{/each}</div></section>{:else}<ChatMessages {messages} {loading}/>{/if}
 <ChatInput onSend={send} onCancel={cancel} disabled={false} streaming={loading}/>
 </main>
 <aside bind:this={inspectorElement} data-open="false" inert class="inspector-shell"><button class="sheet-close" aria-label="Close inspector" onclick={() => setOverlay(inspectorElement, inspectorScrim, false)}>×</button><Inspector {stats} {artifacts} {context} {logs} active={activeTab} onTab={(t)=>activeTab=t} onOpenArtifact={()=>artifactOpen=true}/></aside>
 <button bind:this={inspectorScrim} class="sheet-scrim" aria-label="Close inspector" tabindex="-1" onclick={() => setOverlay(inspectorElement, inspectorScrim, false)}></button>
 {#if artifactOpen}<ArtifactPanel {artifacts} onClose={()=>artifactOpen=false}/>{/if}
</div>
