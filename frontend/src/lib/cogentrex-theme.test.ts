import { describe, expect, it } from 'vitest';
import { COGENTREX_THEME, LEARNING_KIND_COLORS } from './cogentrex-theme';

describe('Cogentrex Evidence Dark theme', () => {
  it('exposes the approved dark canvas and orange identity colors', () => {
    expect(COGENTREX_THEME.canvas).toBe('#050712');
    expect(COGENTREX_THEME.surface).toBe('#0a1022');
    expect(COGENTREX_THEME.text).toBe('#f4f7fb');
    expect(COGENTREX_THEME.orange).toBe('#f6b44b');
  });

  it('uses orange for identity while retaining semantic state colors', () => {
    expect(LEARNING_KIND_COLORS.frontend).toBe(COGENTREX_THEME.orange);
    expect(LEARNING_KIND_COLORS.backend).toBe(COGENTREX_THEME.blue);
    expect(LEARNING_KIND_COLORS.database).toBe(COGENTREX_THEME.purple);
    expect(LEARNING_KIND_COLORS.security).toBe(COGENTREX_THEME.coral);
    expect(new Set(Object.values(LEARNING_KIND_COLORS)).size).toBeGreaterThan(3);
  });
});
