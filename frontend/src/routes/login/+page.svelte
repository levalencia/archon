<script lang="ts">
  let mode = $state<'login' | 'register'>('login');
  let username = $state('');
  let password = $state('');
  let email = $state('');
  let error = $state('');
  let loading = $state(false);

  async function handleSubmit() {
    error = '';
    loading = true;

    const endpoint = mode === 'login' ? '/api/auth/login' : '/api/auth/register';
    const body: any = { username, password };
    if (mode === 'register') body.email = email;

    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      const data = await res.json();

      if (data.access_token) {
        localStorage.setItem('archon_token', data.access_token);
        localStorage.setItem('archon_user', JSON.stringify({
          user_id: data.user_id,
          username: data.username,
        }));
        window.location.href = '/';
      } else {
        error = data.error || 'Authentication failed';
      }
    } catch {
      error = 'Cannot connect to server';
    } finally {
      loading = false;
    }
  }
</script>

<div class="min-h-screen bg-[var(--bg-primary)] flex items-center justify-center">
  <div class="w-full max-w-md p-8">
    <!-- Logo -->
    <div class="text-center mb-8">
      <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--purple)] flex items-center justify-center text-3xl font-bold text-white mx-auto mb-4">
        A
      </div>
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Archon</h1>
      <p class="text-sm text-[var(--text-secondary)] mt-1">Production AI Agent</p>
    </div>

    <!-- Form card -->
    <div class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-2xl p-6">
      <!-- Tabs -->
      <div class="flex mb-6 bg-[var(--bg-tertiary)] rounded-lg p-1">
        <button
          onclick={() => { mode = 'login'; error = ''; }}
          class="flex-1 py-2 rounded-md text-sm font-medium transition-all cursor-pointer
            {mode === 'login'
              ? 'bg-[var(--accent-glow)] text-[var(--accent)]'
              : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'}"
        >
          Sign In
        </button>
        <button
          onclick={() => { mode = 'register'; error = ''; }}
          class="flex-1 py-2 rounded-md text-sm font-medium transition-all cursor-pointer
            {mode === 'register'
              ? 'bg-[var(--accent-glow)] text-[var(--accent)]'
              : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'}"
        >
          Register
        </button>
      </div>

      <!-- Error -->
      {#if error}
        <div class="mb-4 px-4 py-2 bg-[rgba(248,81,73,0.1)] border border-[var(--error)] rounded-lg text-sm text-[var(--error)]">
          {error}
        </div>
      {/if}

      <!-- Fields -->
      <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
        <div class="space-y-4">
          <div>
            <label class="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">Username</label>
            <input
              type="text"
              bind:value={username}
              required
              minlength="3"
              class="w-full px-4 py-2.5 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm outline-none focus:border-[var(--accent)] transition-colors"
              placeholder="Enter username"
            />
          </div>

          {#if mode === 'register'}
            <div>
              <label class="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">Email</label>
              <input
                type="email"
                bind:value={email}
                class="w-full px-4 py-2.5 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm outline-none focus:border-[var(--accent)] transition-colors"
                placeholder="Optional"
              />
            </div>
          {/if}

          <div>
            <label class="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">Password</label>
            <input
              type="password"
              bind:value={password}
              required
              minlength="6"
              class="w-full px-4 py-2.5 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg text-[var(--text-primary)] text-sm outline-none focus:border-[var(--accent)] transition-colors"
              placeholder="Enter password"
            />
          </div>

          <button
            type="submit"
            disabled={loading || !username || !password}
            class="w-full py-2.5 rounded-lg text-sm font-medium transition-all cursor-pointer
              {loading
                ? 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] cursor-not-allowed'
                : 'bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)]'}"
          >
            {loading ? '...' : mode === 'login' ? 'Sign In' : 'Create Account'}
          </button>
        </div>
      </form>
    </div>

    <p class="text-center text-[11px] text-[var(--text-muted)] mt-4">
      100% local · Ollama · Zero cloud dependencies
    </p>
  </div>
</div>
