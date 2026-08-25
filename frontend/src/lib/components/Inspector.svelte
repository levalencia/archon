<script lang="ts">
 import type { Artifact, ContextStats, InspectorTab, LogEntry, RunStats } from '$lib/types';
 let { stats, artifacts = [], context, logs = [], active = 'run', onTab = (_t: InspectorTab) => {}, onOpenArtifact = () => {} }: { stats: RunStats; artifacts?: Artifact[]; context?: ContextStats; logs?: LogEntry[]; active?: InspectorTab; onTab?: (tab: InspectorTab) => void; onOpenArtifact?: () => void } = $props();
 const tabs: InspectorTab[] = ['run','evidence','context','logs'];
</script>
<div class="inspector">
 <header><div><p class="eyebrow">Inspector</p><h2>Run details</h2></div><span class="live"><i></i> Live</span></header>
 <div class="tabs" role="tablist">{#each tabs as tab}<button role="tab" aria-selected={active === tab} onclick={() => onTab(tab)}>{tab[0].toUpperCase()+tab.slice(1)}</button>{/each}</div>
 <div class="inspector-content">
 {#if active === 'run'}
  <p class="section-label">Current run</p><div class="stat-grid"><div><span>Latency</span><strong>{stats.latency}</strong></div><div><span>Tokens</span><strong>{stats.tokens}</strong></div><div><span>Tools</span><strong>{stats.tools}</strong></div><div><span>Iterations</span><strong>{stats.iterations}</strong></div></div>
  <section class="health"><h3>Reliability signals</h3><div><span class="status-dot"></span><span>LLM provider</span><strong>Healthy</strong></div><div><span class="status-dot"></span><span>Vector database</span><strong>Healthy</strong></div></section>
 {:else if active === 'evidence'}
  <p class="section-label">Generated artifacts</p>{#if artifacts.length}<button class="artifact-card" onclick={onOpenArtifact}><strong>{artifacts[0].title}</strong><span>{artifacts.length} available · Open preview</span></button>{:else}<div class="empty-detail">Sources, tool output, and artifacts from the run appear here.</div>{/if}
 {:else if active === 'context'}
  <p class="section-label">Context window</p><div class="context-meter"><div><span>Utilization</span><strong>{context?.utilization_pct || 0}%</strong></div><progress max="100" value={context?.utilization_pct || 0}></progress><small>{context?.tokens?.toLocaleString() || 0} of {context?.budget?.toLocaleString() || 0} tokens</small></div>
 {:else}
  <div class="log-toolbar"><span>{logs.length} events</span><button onclick={() => navigator.clipboard?.writeText(logs.map(l => `${l.ts || ''} [${l.level || ''}] ${l.event || ''} ${l.data ? JSON.stringify(l.data) : ''}`).join('\n'))}>Copy logs</button></div><div class="log-list">{#if logs.length === 0}<div class="empty-detail">Waiting for backend events…</div>{/if}{#each logs as log}<div><time>{log.ts}</time><strong class:error-text={log.level === 'error'}>{log.level}</strong><span>{log.event}{#if log.data && Object.keys(log.data).length > 0} <span style="color:var(--muted);font-size:9px">{Object.entries(log.data).map(([k,v]) => `${k}=${v}`).join(' ')}</span>{/if}</span></div>{/each}</div>
 {/if}
 </div>
</div>
