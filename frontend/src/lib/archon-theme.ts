export const ARCHON_THEME = {
  canvas: '#050b16',
  surface: '#0f172a',
  surfaceRaised: '#111c2e',
  border: '#334155',
  text: '#f8fafc',
  textSecondary: '#cbd5e1',
  textMuted: '#94a3b8',
  orange: '#f59e0b',
  orangeStrong: '#d97706',
  green: '#22c55e',
  blue: '#3b82f6',
  purple: '#a78bfa',
  coral: '#fb7185',
} as const;

export const LEARNING_KIND_COLORS: Readonly<Record<string, string>> = {
  frontend: ARCHON_THEME.orange,
  backend: ARCHON_THEME.blue,
  database: ARCHON_THEME.purple,
  security: ARCHON_THEME.coral,
  external: ARCHON_THEME.textMuted,
  root: ARCHON_THEME.orange,
};
