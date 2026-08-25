const TOKEN_KEY = 'archon_token';
const USER_KEY = 'archon_user';

export function authHeaders(headers: HeadersInit = {}): Headers {
  const result = new Headers(headers);
  if (typeof localStorage !== 'undefined') {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) result.set('Authorization', `Bearer ${token}`);
  }
  return result;
}

export function authenticatedFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  return fetch(input, {
    ...init,
    credentials: 'same-origin',
    headers: authHeaders(init.headers),
  });
}

export function isAuthenticated(): boolean {
  if (typeof localStorage === 'undefined') return false;
  return !!localStorage.getItem(TOKEN_KEY);
}

export function getUser(): { user_id: string; username: string } | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function logout() {
  if (typeof localStorage === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  window.location.href = '/login';
}
