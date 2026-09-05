import { describe, expect, it } from 'vitest';
import { githubSourceHref, sourceLabel } from './source-links';

const commit = 'a'.repeat(40);

describe('learning source links', () => {
  it('builds a commit-pinned GitHub URL for repository-relative documentation', () => {
    expect(githubSourceHref('docs/course/modules/05-policy-and-approvals/README.md', commit)).toBe(
      `https://github.com/levalencia/archon/blob/${commit}/docs/course/modules/05-policy-and-approvals/README.md`,
    );
  });

  it('adds validated line anchors when a structured source includes them', () => {
    expect(githubSourceHref({ path: 'README.md', line_start: 20, line_end: 28 }, commit)).toBe(
      `https://github.com/levalencia/archon/blob/${commit}/README.md#L20-L28`,
    );
  });

  it.each(['../README.md', '/etc/passwd', 'https://example.com/x', 'docs/../README.md'])('rejects unsafe source paths: %s', path => {
    expect(() => githubSourceHref(path, commit)).toThrow('unsafe learning source path');
  });

  it('uses a human-readable label instead of exposing a raw path', () => {
    expect(sourceLabel({ path: 'docs/course/modules/05-policy-and-approvals/README.md', label: 'Policy and approvals' })).toBe(
      'Policy and approvals',
    );
    expect(sourceLabel('docs/IMPLEMENTATION-EVIDENCE.md')).toBe('Implementation Evidence');
  });
});
