<script lang="ts">
  import { LogIn, UserPlus, Eye, EyeOff } from 'lucide-svelte';

  let mode = $state<'login' | 'register'>('login');
  let username = $state('');
  let password = $state('');
  let email = $state('');
  let error = $state('');
  let loading = $state(false);
  let showPassword = $state(false);

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

<div class="min-h-screen bg-[var(--bg-primary)] flex items-center justify-center p-4">
  <div class="w-full max-w-md">
    <!-- Logo -->
    <div class="text-center mb-8">
      <div class="w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--accent)] to-[var(--purple)]
        flex items-center justify-center text-3xl font-bold text-white mx-auto mb-4
        shadow-[0_0_30px_rgba(56,189,248,0.2)]">
        A
      </div>
      <h1 class="text-2xl font-semibold text-[var(--text-primary)]">Archon</h1>
      <p class="text-sm text-[var(--text-secondary)] mt-1">Production AI Agent</p>
    </div>

    <!-- Form card -->
    <div class="bg-[var(--bg-secondary)] border border-[var(--border)] rounded-2xl p-6
      shadow-[0_4px_24px_rgba(0,0,0,0.3)]">
      <!-- Tabs -->
      <div class="flex mb-6 bg-[var(--bg-tertiary)] rounded-lg p-1">
        <button
          onclick={() => { mode = 'login'; error = ''; }}
          class="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-md text-sm font-medium transition-all cursor-pointer
            {mode === 'login'
              ? 'bg-[var(--accent-glow)] text-[var(--accent)] shadow-sm'
              : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'}"
        >
          <LogIn size={14} />
          Sign In
        </button>
        <button
          onclick={() => { mode = 'register'; error = ''; }}
          class="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-md text-sm font-medium transition-all cursor-pointer
            {mode === 'register'
              ? 'bg-[var(--accent-glow)] text-[var(--accent)] shadow-sm'
              : 'text-[var(--text-muted)] hover:text-[var(--text-primary)]'}"
        >
          <UserPlus size={14} />
          Register
        </button>
      </div>

      <!-- Error -->
      {#if error}
        <div class="mb-4 px-4 py-2.5 bg-[rgba(248,81,73,0.1)] border border-[var(--error)]
          rounded-lg text-sm text-[var(--error)] flex items-center gap-2">
          <span class="shrink-0 w-1.5 h-1.5 rounded-full bg-[var(--error)]"></span>
          {error}
        </div>
      {/if}

      <!-- Fields -->
      <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
        <div class="space-y-4">
          <div>
            <label for="username" class="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">
              Username
            </label>
            <input
              id="username"
              type="text"
              bind:value={username}
              required
              minlength="3"
              autocomplete="username"
              class="w-full px-4 py-2.5 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg
                text-[var(--text-primary)] text-sm outline-none focus:border-[var(--accent)]
                transition-colors placeholder:text-[var(--text-muted)]"
              placeholder="Enter username"
            />
          </div>

          {#if mode === 'register'}
            <div>
              <label for="email" class="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">
                Email
              </label>
              <input
                id="email"
                type="email"
                bind:value={email}
                autocomplete="email"
                class="w-full px-4 py-2.5 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg
                  text-[var(--text-primary)] text-sm outline-none focus:border-[var(--accent)]
                  transition-colors placeholder:text-[var(--text-muted)]"
                placeholder="Optional"
              />
            </div>
          {/if}

          <div>
            <label for="password" class="block text-xs font-medium text-[var(--text-secondary)] mb-1.5">
              Password
            </label>
            <div class="relative">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                bind:value={password}
                required
                minlength="6"
                autocomplete={mode === 'login' ? 'current-password' : 'new-password'}
                class="w-full px-4 py-2.5 pr-10 bg-[var(--bg-primary)] border border-[var(--border)] rounded-lg
                  text-[var(--text-primary)] text-sm outline-none focus:border-[var(--accent)]
                  transition-colors placeholder:text-[var(--text-muted)]"
                placeholder="Enter password"
              />
              <button
                type="button"
                onclick={() => showPassword = !showPassword}
                class="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]
                  hover:text-[var(--text-secondary)] transition-colors cursor-pointer"
                tabindex="-1"
              >
                {#if showPassword}
                  <EyeOff size={16} />
                {:else}
                  <Eye size={16} />
                {/if}
              </button>
            </div>
          </div>

          <button
            type="submit"
            disabled={loading || !username || !password}
            class="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-sm font-medium
              transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed
              {loading
                ? 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'
                : 'bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] shadow-[0_0_12px_rgba(56,189,248,0.15)]'}"
          >
            {#if loading}
              <span class="w-4 h-4 border-2 border-[var(--text-muted)] border-t-transparent rounded-full animate-spin"></span>
              Processing…
            {:else if mode === 'login'}
              <LogIn size={14} />
              Sign In
            {:else}
              <UserPlus size={14} />
              Create Account
            {/if}
          </button>
        </div>
      </form>
    </div>

    <p class="text-center text-[11px] text-[var(--text-muted)] mt-4">
      100% local · Ollama · Zero cloud dependencies
    </p>
  </div>
</div>
