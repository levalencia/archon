import { authenticatedFetch } from '$lib/auth';

export type SandboxStatus = {
  enabled: boolean;
  available: boolean;
  isolation: 'runner-container' | 'disabled';
  kinds: string[];
  network_access: boolean;
  timeout_seconds: number;
  output_bytes: number;
  memory_mb: number;
  pids_limit: number;
  cpus: number;
};

export async function getSandboxStatus(): Promise<SandboxStatus> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5_000);
  try {
    const response = await authenticatedFetch('/api/sandbox/status', { signal: controller.signal });
    if (!response.ok) throw new Error(`Sandbox status unavailable (${response.status})`);
    return await response.json() as SandboxStatus;
  } catch (cause) {
    if (controller.signal.aborted) throw new Error('Sandbox status timed out');
    throw cause;
  } finally {
    clearTimeout(timeout);
  }
}
