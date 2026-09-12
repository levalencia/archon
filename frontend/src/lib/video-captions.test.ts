import { describe, expect, it } from 'vitest';

import { buildVideoCaptions } from './video-captions';

describe('buildVideoCaptions', () => {
  it('uses authored segment timing when every segment is timed', () => {
    const captions = buildVideoCaptions([
      { text: 'Factory overview.', start_seconds: 40.076, end_seconds: 77.42 },
      { text: 'Middleware onion.', start_seconds: 347.656, end_seconds: 409.84 },
    ], 679.748);

    expect(captions).toContain('00:00:40.076 --> 00:01:17.420');
    expect(captions).toContain('00:05:47.656 --> 00:06:49.840');
  });

  it('uses the real video duration when transcript timing is unavailable', () => {
    const captions = buildVideoCaptions([
      { text: 'First chapter.' },
      { text: 'Second chapter.' },
    ], 120);

    expect(captions).toContain('00:00:00.000 --> 00:01:00.000');
    expect(captions).toContain('00:01:00.000 --> 00:02:00.000');
  });
});
