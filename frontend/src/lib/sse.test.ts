import { describe, expect, it } from 'vitest';
import { SSEParser } from './sse';

describe('SSEParser', () => {
  it('parses events split at arbitrary chunk boundaries', () => {
    const parser = new SSEParser();
    expect(parser.push('eve')).toEqual([]);
    expect(parser.push('nt: token\r\nda')).toEqual([]);
    expect(parser.push('ta: hel')).toEqual([]);
    expect(parser.push('lo\r\n\r\n')).toEqual([{ event: 'token', data: 'hello', id: undefined }]);
  });
  it('joins multiline data and ignores heartbeat comments', () => {
    const parser = new SSEParser();
    expect(parser.push(': ping\n\nevent: thinking\ndata: first\ndata: second\n\n')).toEqual([
      { event: 'thinking', data: 'first\nsecond', id: undefined }
    ]);
  });
  it('flushes a final event without trailing separator', () => {
    const parser = new SSEParser();
    expect(parser.push('event: done\ndata: {"ok":true}', true)[0].event).toBe('done');
  });
});
