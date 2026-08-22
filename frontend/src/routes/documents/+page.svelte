<script lang="ts">
  let documents: any[] = $state([]);
  let dragOver = $state(false);
  let uploading = $state(false);
  let queryText = $state('');
  let queryResult: any = $state(null);

  async function loadDocuments() {
    const r = await fetch('/api/documents');
    documents = await r.json();
  }

  async function uploadFile(file: File) {
    uploading = true;
    const text = await file.text();
    const r = await fetch('/api/documents/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: file.name, content: text, source: file.name }),
    });
    if (r.ok) await loadDocuments();
    uploading = false;
  }

  function handleDrop(e: DragEvent) {
    e.preventDefault();
    dragOver = false;
    const file = e.dataTransfer?.files[0];
    if (file) uploadFile(file);
  }

  function handleFileInput(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    if (file) uploadFile(file);
  }

  async function queryDocuments() {
    if (!queryText.trim()) return;
    const r = await fetch('/api/documents/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: queryText }),
    });
    queryResult = await r.json();
  }

  async function deleteDoc(id: string) {
    await fetch(`/api/documents/${id}`, { method: 'DELETE' });
    await loadDocuments();
  }

  $effect(() => { loadDocuments(); });
</script>

<div class="max-w-4xl mx-auto p-6">
  <h1 class="text-xl font-semibold text-[var(--text-primary)] mb-6">📄 Documents & RAG</h1>

  <!-- Upload zone -->
  <div
    role="button"
    tabindex="0"
    ondragover={(e) => { e.preventDefault(); dragOver = true; }}
    ondragleave={() => dragOver = false}
    ondrop={handleDrop}
    class="border-2 border-dashed rounded-xl p-8 text-center mb-6 transition-colors cursor-pointer
      {dragOver ? 'border-[var(--accent)] bg-[var(--accent-glow)]' : 'border-[var(--border)] bg-[var(--bg-secondary)]'}"
  >
    <div class="text-3xl mb-2">{uploading ? '⏳' : '📎'}</div>
    <div class="text-sm text-[var(--text-secondary)]">
      {uploading ? 'Uploading...' : 'Drag & drop a file here, or click to browse'}
    </div>
    <div class="text-xs text-[var(--text-muted)] mt-1">Supports .txt, .md, .pdf, .json</div>
    <input type="file" onchange={handleFileInput} class="hidden" accept=".txt,.md,.pdf,.json,.csv" />
  </div>

  <!-- Document list -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5 mb-6">
    <h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">
      Indexed Documents ({documents.length})
    </h2>
    {#if documents.length === 0}
      <div class="text-sm text-[var(--text-muted)]">No documents uploaded yet</div>
    {:else}
      <div class="space-y-2">
        {#each documents as doc}
          <div class="flex items-center justify-between px-4 py-3 bg-[var(--bg-tertiary)] rounded-lg">
            <div>
              <div class="text-sm text-[var(--text-primary)]">{doc.title}</div>
              <div class="text-xs text-[var(--text-muted)]">
                {doc.chunks} chunks · {doc.characters} chars · {doc.source}
              </div>
            </div>
            <button
              onclick={() => deleteDoc(doc.id)}
              class="text-xs text-[var(--text-muted)] hover:text-[var(--error)] cursor-pointer px-2"
            >
              🗑
            </button>
          </div>
        {/each}
      </div>
    {/if}
  </section>

  <!-- RAG Query -->
  <section class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-xl p-5">
    <h2 class="text-base font-semibold text-[var(--text-primary)] mb-4">🔍 Query Documents</h2>
    <div class="flex gap-2 mb-4">
      <input
        type="text"
        bind:value={queryText}
        placeholder="Ask a question about your documents..."
        class="flex-1 px-4 py-2 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
        onkeydown={(e) => e.key === 'Enter' && queryDocuments()}
      />
      <button
        onclick={queryDocuments}
        class="px-4 py-2 bg-[var(--accent)] text-white rounded-lg text-sm hover:bg-[var(--accent-hover)] cursor-pointer"
      >
        Search
      </button>
    </div>

    {#if queryResult}
      <div class="bg-[var(--bg-tertiary)] rounded-lg p-4">
        <div class="text-sm text-[var(--text-primary)] mb-3">{queryResult.answer}</div>
        <div class="text-xs text-[var(--text-muted)]">
          {queryResult.chunks_retrieved} chunks · confidence: {queryResult.confidence}
        </div>
        {#if queryResult.sources?.length > 0}
          <div class="flex gap-2 mt-2 flex-wrap">
            {#each queryResult.sources as src}
              <span class="px-2 py-1 bg-[var(--bg-primary)] rounded text-xs text-[var(--text-secondary)]">
                📄 {src.title} ({src.score.toFixed(2)})
              </span>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </section>
</div>
