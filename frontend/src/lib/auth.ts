const TOKEN_KEY = 'archon_token';

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