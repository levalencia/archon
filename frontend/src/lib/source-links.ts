export type SourceReference =
  | string
  | {
      path: string;
      label?: string;
      section?: string;
      line_start?: number;
      line_end?: number;
      why_relevant?: string;
    };

const GITHUB_SOURCE_BASE = 'https://github.com/levalencia/cogentrex/blob';

function sourcePath(source: SourceReference): string {
  return typeof source === 'string' ? source : source.path;
}

function validateSourcePath(path: string): void {
  if (
    !path ||
    path.startsWith('/') ||
    path.includes('\\') ||
    path.split('/').includes('..') ||
    /^[a-z][a-z0-9+.-]*:/i.test(path) ||
    path.includes('\0')
  ) {
    throw new Error('unsafe learning source path');
  }
}

export function githubSourceHref(source: SourceReference, sourceCommit: string): string {
  const path = sourcePath(source);
  validateSourcePath(path);
  if (!/^[0-9a-f]{40}$/.test(sourceCommit)) throw new Error('invalid learning source commit');
  const encodedPath = path.split('/').map(encodeURIComponent).join('/');
  let anchor = '';
  if (typeof source !== 'string' && source.line_start !== undefined) {
    if (!Number.isInteger(source.line_start) || source.line_start < 1) throw new Error('invalid learning source line');
    anchor = `#L${source.line_start}`;
    if (source.line_end !== undefined) {
      if (!Number.isInteger(source.line_end) || source.line_end < source.line_start) throw new Error('invalid learning source line');
      anchor += `-L${source.line_end}`;
    }
  }
  return `${GITHUB_SOURCE_BASE}/${sourceCommit}/${encodedPath}${anchor}`;
}

export function sourceLabel(source: SourceReference): string {
  if (typeof source !== 'string' && source.label) return source.label;
  const path = sourcePath(source);
  const filename = path.split('/').at(-1) ?? path;
  const stem = filename.toLowerCase() === 'readme.md' ? path.split('/').at(-2) ?? 'README' : filename.replace(/\.[^.]+$/, '');
  return stem
    .split(/[-_]/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(' ');
}

export function sourceWhy(source: SourceReference): string | undefined {
  return typeof source === 'string' ? undefined : source.why_relevant;
}
