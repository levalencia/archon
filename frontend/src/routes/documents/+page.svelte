<script lang="ts">
  import { authenticatedFetch } from '$lib/auth';
  import { FileText, Upload, Search, Trash2, File as FileIcon, Loader } from 'lucide-svelte';

  let documents: any[] = $state([]);
  let dragOver = $state(false);
  let uploading = $state(false);
  let queryText = $state('');
  let queryResult: any = $state(null);
  let querying = $state(false);
  let fileInput: HTMLInputElement;

  async function loadDocuments() {
    const r = await authenticatedFetch('/api/documents');
    documents = await r.json();
  }

  async function uploadFile(file: File) {
    uploading = true;
    const text = await file.text();
    const r = await authenticatedFetch('/api/documents/upload', {
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
    querying = true;
    const r = await authenticatedFetch('/api/documents/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: queryText }),
    });
    queryResult = await r.json();
    querying = false;
  }

  async function deleteDoc(id: string) {
    await authenticatedFetch(`/api/documents/${id}`, { method: 'DELETE' });
    await loadDocuments();
  }

  $effect(() => { loadDocuments(); });
</script>

<div class="page-container">
  <header class="page-header">
    <div class="page-title">
      <FileText size={22} strokeWidth={2} class="icon-accent" />
      <h1>Documents & RAG</h1>
    </div>
  </header>

  <!-- Upload Zone -->
  <button
    type="button"
    ondragover={(e) => { e.preventDefault(); dragOver = true; }}
    ondragleave={() => dragOver = false}
    ondrop={handleDrop}
    onclick={() => fileInput.click()}
    class="upload-zone"
    class:upload-active={dragOver}
    disabled={uploading}
  >
    <div class="upload-icon">
      {#if uploading}
        <Loader size={28} class="icon-muted animate-spin" />
      {:else}
        <Upload size={28} class="icon-accent" />
      {/if}
    </div>
    <div class="upload-text">
      {uploading ? 'Uploading...' : 'Drag & drop a file here, or click to browse'}
    </div>
    <div class="upload-hint">Supports .txt, .md, .pdf, .json, .csv</div>
  </button>
  <input bind:this={fileInput} type="file" onchange={handleFileInput} class="hidden" accept=".txt,.md,.pdf,.json,.csv" />

  <!-- Document List -->
  <section class="card">
    <h2 class="card-title">
      <FileIcon size={16} strokeWidth={2} class="icon-accent" />
      Indexed Documents
      <span class="count-badge">{documents.length}</span>
    </h2>
    {#if documents.length === 0}
      <div class="empty-hint">No documents uploaded yet</div>
    {:else}
      <div class="doc-list">
        {#each documents as doc}
          <div class="doc-row">
            <div class="doc-icon">
              <FileText size={16} class="icon-muted" />
            </div>
            <div class="doc-info">
              <div class="doc-name">{doc.title}</div>
              <div class="doc-meta">
                {doc.chunks} chunks · {doc.characters} chars · {doc.source}
              </div>
            </div>
            <button onclick={() => deleteDoc(doc.id)} class="delete-btn" title="Delete document">
              <Trash2 size={14} />
            </button>
          </div>
        {/each}
      </div>
    {/if}
  </section>

  <!-- RAG Query -->
  <section class="card">
    <h2 class="card-title">
      <Search size={16} strokeWidth={2} class="icon-accent" />
      Query Documents
    </h2>
    <div class="query-bar">
      <input
        type="text"
        bind:value={queryText}
        placeholder="Ask a question about your documents..."
        class="query-input"
        onkeydown={(e) => e.key === 'Enter' && queryDocuments()}
      />
      <button onclick={queryDocuments} class="btn-primary" disabled={querying || !queryText.trim()}>
        {#if querying}
          <Loader size={14} class="animate-spin" />
        {:else}
          <Search size={14} />
        {/if}
        Search
      </button>
    </div>

    {#if queryResult}
      <div class="query-result">
        <div class="result-answer">{queryResult.answer}</div>
        <div class="result-meta">
          {queryResult.chunks_retrieved} chunks · confidence: {queryResult.confidence}
        </div>
        {#if queryResult.sources?.length > 0}
          <div class="result-sources">
            {#each queryResult.sources as src}
              <span class="source-tag">
                <FileText size={11} />
                {src.title} ({src.score.toFixed(2)})
              </span>
            {/each}
          </div>
        {/if}
      </div>
    {/if}
  </section>
</div>

<style>
  .page-container {
    max-width: 56rem;
    margin: 0 auto;
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .page-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .page-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .page-title h1 {
    font-size: 1.25rem;
    font-weight: 600;
    color: var(--text-primary);
  }

  /* Upload Zone */
  .upload-zone {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.5rem;
    padding: 2.5rem 1.5rem;
    border: 2px dashed var(--border);
    border-radius: 0.75rem;
    background: var(--bg-secondary);
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    width: 100%;
  }

  .upload-zone:hover {
    border-color: var(--accent);
    background: var(--bg-tertiary);
  }

  .upload-zone.upload-active {
    border-color: var(--accent);
    background: var(--accent-glow);
  }

  .upload-zone:disabled {
    cursor: wait;
    opacity: 0.7;
  }

  .upload-icon {
    margin-bottom: 0.25rem;
  }

  .upload-text {
    font-size: 0.875rem;
    color: var(--text-secondary);
  }

  .upload-hint {
    font-size: 0.75rem;
    color: var(--text-muted);
  }

  .hidden { display: none; }

  /* Card */
  .card {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 0.75rem;
    padding: 1.25rem;
  }

  .card-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.9375rem;
    font-weight: 600;
    color: var(--text-primary);
    margin-bottom: 1rem;
  }

  .count-badge {
    font-size: 0.6875rem;
    font-weight: 500;
    padding: 0.0625rem 0.5rem;
    border-radius: 9999px;
    background: var(--bg-tertiary);
    color: var(--text-muted);
  }

  .empty-hint {
    font-size: 0.875rem;
    color: var(--text-muted);
  }

  /* Document List */
  .doc-list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .doc-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    background: var(--bg-tertiary);
    border-radius: 0.5rem;
    transition: background 0.15s;
  }

  .doc-row:hover {
    background: var(--bg-hover);
  }

  .doc-icon {
    flex-shrink: 0;
  }

  .doc-info {
    flex: 1;
    min-width: 0;
  }

  .doc-name {
    font-size: 0.875rem;
    color: var(--text-primary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .doc-meta {
    font-size: 0.75rem;
    color: var(--text-muted);
    margin-top: 0.125rem;
  }

  .delete-btn {
    flex-shrink: 0;
    padding: 0.375rem;
    color: var(--text-muted);
    cursor: pointer;
    border-radius: 0.375rem;
    background: transparent;
    border: none;
    transition: color 0.15s, background 0.15s;
  }

  .delete-btn:hover {
    color: var(--error);
    background: rgba(248, 81, 73, 0.1);
  }

  /* Query */
  .query-bar {
    display: flex;
    gap: 0.5rem;
    margin-bottom: 1rem;
  }

  .query-input {
    flex: 1;
    padding: 0.5rem 1rem;
    background: var(--bg-primary);
    border: 1px solid var(--border);
    border-radius: 0.5rem;
    font-size: 0.875rem;
    color: var(--text-primary);
    outline: none;
    transition: border-color 0.15s;
  }

  .query-input:focus {
    border-color: var(--accent);
  }

  .query-input::placeholder {
    color: var(--text-muted);
  }

  .btn-primary {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.5rem 1rem;
    background: var(--accent);
    color: white;
    border: none;
    border-radius: 0.5rem;
    font-size: 0.875rem;
    cursor: pointer;
    transition: background 0.15s;
    white-space: nowrap;
  }

  .btn-primary:hover:not(:disabled) {
    background: var(--accent-hover);
  }

  .btn-primary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  /* Query Result */
  .query-result {
    background: var(--bg-tertiary);
    border-radius: 0.5rem;
    padding: 1rem;
  }

  .result-answer {
    font-size: 0.875rem;
    color: var(--text-primary);
    margin-bottom: 0.75rem;
    line-height: 1.5;
  }

  .result-meta {
    font-size: 0.75rem;
    color: var(--text-muted);
  }

  .result-sources {
    display: flex;
    gap: 0.5rem;
    margin-top: 0.5rem;
    flex-wrap: wrap;
  }

  .source-tag {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    padding: 0.25rem 0.5rem;
    background: var(--bg-primary);
    border-radius: 0.25rem;
    font-size: 0.75rem;
    color: var(--text-secondary);
  }

  :global(.icon-accent) { color: var(--accent); }
  :global(.icon-muted) { color: var(--text-muted); }
  :global(.animate-spin) { animation: spin 1s linear infinite; }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }
</style>
