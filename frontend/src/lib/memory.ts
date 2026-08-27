import { authenticatedFetch } from '$lib/auth';

export type MemoryRotationStatus = {
  project_id: string;
  active_version: number;
  version_counts: Record<string, number>;
  remaining: number;
  complete: boolean;
  retirement_requires_legacy_writer_drain: boolean;
  rotated?: number;
};

async function rotationRequest(
  projectId: string,
  init?: RequestInit,
): Promise<MemoryRotationStatus> {
  const response = await authenticatedFetch(
    `/api/memory/rotation?project_id=${encodeURIComponent(projectId)}`,
    init,
  );
  if (!response.ok) {
    throw new Error(`Memory rotation request failed (${response.status})`);
  }
  return response.json() as Promise<MemoryRotationStatus>;
}

export const getMemoryRotation = (projectId = 'default') => rotationRequest(projectId);

export const rotateMemoryKeys = (projectId = 'default', batchSize = 100) =>
  rotationRequest(projectId, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ batch_size: batchSize }),
  });
