export interface SSEEvent { event: string; data: string; id?: string }

/** Incremental SSE parser. Handles CRLF, comments, multiline data, and boundaries split across chunks. */
export class SSEParser {
  private buffer = '';
  private event = '';
  private id: string | undefined;
  private data: string[] = [];

  push(chunk: string, flush = false): SSEEvent[] {
    this.buffer += chunk;
    const out: SSEEvent[] = [];
    const lines = this.buffer.split(/\r?\n/);
    this.buffer = flush ? '' : (lines.pop() ?? '');
    if (flush && this.buffer) lines.push(this.buffer);
    for (const line of lines) {
      if (line === '') {
        if (this.data.length) out.push({ event: this.event || 'message', data: this.data.join('\n'), id: this.id });
        this.event = ''; this.data = [];
        continue;
      }
      if (line.startsWith(':')) continue;
      const colon = line.indexOf(':');
      const field = colon < 0 ? line : line.slice(0, colon);
      let value = colon < 0 ? '' : line.slice(colon + 1);
      if (value.startsWith(' ')) value = value.slice(1);
      if (field === 'event') this.event = value;
      else if (field === 'data') this.data.push(value);
      else if (field === 'id') this.id = value;
    }
    if (flush && this.data.length) {
      out.push({ event: this.event || 'message', data: this.data.join('\n'), id: this.id });
      this.event = ''; this.data = [];
    }
    return out;
  }
}
