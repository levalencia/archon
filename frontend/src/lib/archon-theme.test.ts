import { describe, expect, it } from 'vitest';
import { ARCHON_THEME, LEARNING_KIND_COLORS } from './archon-theme';

describe('Archon Evidence Dark theme', () => {
  it('exposes the approved dark canvas and orange identity colors', () => {
    expect(ARCHON_THEME.canvas).toBe('#050b16');
    expect(ARCHON_THEME.surface).toBe('#0f172a');
    expect(ARCHON_THEME.text).toBe('#f8fafc');
    expect(ARCHON_THEME.orange).toBe('#f59e0b');
  });

  it('uses orange for identity while retaining semantic state colors', () => {
    expect(LEARNING_KIND_COLORS.frontend).toBe(ARCHON_THEME.orange);
    expect(LEARNING_KIND_COLORS.backend).toBe(ARCHON_THEME.blue);
    expect(LEARNING_KIND_COLORS.database).toBe(ARCHON_THEME.purple);
    expect(LEARNING_KIND_COLORS.security).toBe(ARCHON_THEME.coral);
    expect(new Set(Object.values(LEARNING_KIND_COLORS)).size).toBeGreaterThan(3);
  });
});
