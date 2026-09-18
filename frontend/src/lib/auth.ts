const TOKEN_KEY = 'cogentrex_token';
const USER_KEY = 'cogentrex_user';

export type AuthUser = {
  user_id: string;
  username: string;
  email: string | null;
  is_admin: boolean;
};

export function authHeaders(headers: HeadersInit = {}): Headers {
  const result = new Headers(headers);
  if (typeof localStorage !== 'undefined') {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) result.set('Authorization', `Bearer ${token}`);
  }
  return result;
}

export async function authenticatedFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const response = await fetch(input, {
    ...init,
    credentials: 'same-origin',
    headers: authHeaders(init.headers),
  });
  if (response.status === 401) logout();
  return response;
}

export function isAuthenticated(): boolean {
  if (typeof localStorage === 'undefined') return false;
  return !!localStorage.getItem(TOKEN_KEY);
}

export function getUser(): AuthUser | null {
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function saveUser(user: AuthUser): void {
  if (typeof localStorage === 'undefined') return;
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function isAdmin(): boolean {
  return getUser()?.is_admin === true;
}

export async function refreshCurrentUser(): Promise<AuthUser | null> {
  const response = await authenticatedFetch('/api/auth/me');
  if (!response.ok) return null;
  const user = (await response.json()) as AuthUser;
  saveUser(user);
  return user;
}

export function logout() {
  if (typeof localStorage === 'undefined') return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  window.location.href = '/login';
}
