export const COGENTREX_THEME = {
  canvas: '#050712',
  surface: '#0a1022',
  surfaceRaised: '#11182d',
  border: '#26324d',
  text: '#f4f7fb',
  textSecondary: '#d2d9e6',
  textMuted: '#a9b4cc',
  orange: '#f6b44b',
  orangeStrong: '#dc8b18',
  green: '#5ef2a0',
  blue: '#6ee7ff',
  purple: '#8b5cf6',
  coral: '#ff6b6b',
} as const;

export const LEARNING_KIND_COLORS: Readonly<Record<string, string>> = {
  frontend: COGENTREX_THEME.orange,
  backend: COGENTREX_THEME.blue,
  database: COGENTREX_THEME.purple,
  security: COGENTREX_THEME.coral,
  external: COGENTREX_THEME.textMuted,
  root: COGENTREX_THEME.orange,
};
