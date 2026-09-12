export interface CaptionSegment {
  text: string;
  start_seconds?: number;
  end_seconds?: number;
}

function stamp(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = (seconds % 60).toFixed(3).padStart(6, '0');
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${remainder}`;
}

export function buildVideoCaptions(segments: CaptionSegment[], durationSeconds = 70): string {
  const timed = segments.length > 0 && segments.every(segment =>
    Number.isFinite(segment.start_seconds) &&
    Number.isFinite(segment.end_seconds) &&
    (segment.end_seconds ?? 0) > (segment.start_seconds ?? 0),
  );
  const cueLength = durationSeconds / Math.max(segments.length, 1);
  const cues = segments.map((segment, index) => {
    const start = timed ? segment.start_seconds! : index * cueLength;
    const end = timed ? segment.end_seconds! : (index + 1) * cueLength;
    const text = segment.text.replace(/\s+/g, ' ').trim();
    return `${index + 1}\n${stamp(start)} --> ${stamp(end)}\n${text}\n`;
  }).join('\n');
  return `WEBVTT\n\n${cues}`;
}
