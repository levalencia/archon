import { authenticatedFetch } from '$lib/auth';

export type LearningArtifactType =
  | 'deck' | 'diagram' | 'infographic' | 'audio' | 'podcast'
  | 'mind-map' | 'flashcards' | 'quiz' | 'study-guide' | 'video';
export type LearningArtifactStatus = 'review-ready' | 'published' | 'stale';

export interface LearningArtifactSummary {
  id: string;
  type: LearningArtifactType;
  title: string;
  status: LearningArtifactStatus;
  language: 'en';
  media_type: string;
  sha256: string;
  source_commit: string;
  limitations: string[];
  duration_seconds?: number;
  transcript_artifact_id?: string;
}

export interface LearningPack {
  id: string;
  title: string;
  purpose: string;
  artifacts: LearningArtifactSummary[];
}

export interface LearningLibraryCatalog {
  schema: 'archon.learning-library';
  version: 1;
  generated_at: string;
  source_commit: string;
  packs: LearningPack[];
}

export interface LearningArtifactDetail extends LearningArtifactSummary {
  content?: unknown;
}

export interface MediaAccess {
  url: string;
  expires_at: number;
}

type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

function validateCatalog(value: unknown): LearningLibraryCatalog {
  const catalog = value as LearningLibraryCatalog;
  if (catalog?.schema !== 'archon.learning-library' || catalog.version !== 1 || !Array.isArray(catalog.packs)) {
    throw new Error('Learning library catalog is invalid');
  }
  for (const pack of catalog.packs) {
    if (!pack.id || !pack.title || !Array.isArray(pack.artifacts)) {
      throw new Error('Learning library catalog contains an invalid pack');
    }
    for (const artifact of pack.artifacts) {
      if (!artifact.id || artifact.language !== 'en' || !['review-ready', 'published', 'stale'].includes(artifact.status)) {
        throw new Error('Learning library catalog contains an invalid artifact');
      }
    }
  }
  return catalog;
}

export async function loadLearningLibrary(fetcher: Fetcher = authenticatedFetch): Promise<LearningLibraryCatalog> {
  const response = await fetcher('/api/learning-media/catalog');
  if (!response.ok) throw new Error(`Learning library request failed (${response.status})`);
  return validateCatalog(await response.json());
}

export async function getLearningArtifact(
  artifactId: string,
  fetcher: Fetcher = authenticatedFetch,
): Promise<LearningArtifactDetail> {
  const response = await fetcher(`/api/learning-media/artifacts/${encodeURIComponent(artifactId)}`);
  if (!response.ok) throw new Error(`Learning artifact request failed (${response.status})`);
  return await response.json() as LearningArtifactDetail;
}

export async function getMediaAccess(
  artifactId: string,
  fetcher: Fetcher = authenticatedFetch,
): Promise<MediaAccess> {
  const response = await fetcher(`/api/learning-media/artifacts/${encodeURIComponent(artifactId)}/access`);
  if (!response.ok) throw new Error(`Learning media access failed (${response.status})`);
  return await response.json() as MediaAccess;
}
