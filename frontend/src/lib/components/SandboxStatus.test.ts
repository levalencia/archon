import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({ getSandboxStatus: vi.fn() }));
vi.mock('$lib/sandbox', () => api);
import SandboxStatus from './SandboxStatus.svelte';

const status = {
  enabled: true,
  available: true,
  isolation: 'runner-container',
  kinds: ['python', 'shell'],
  network_access: false,
  timeout_seconds: 10,
  output_bytes: 65536,
  memory_mb: 128,
  pids_limit: 64,
  cpus: 0.5,
};

afterEach(() => {
  cleanup();
  api.getSandboxStatus.mockReset();
});

describe('SandboxStatus', () => {
  it('renders live isolation policy and refreshes', async () => {
    api.getSandboxStatus.mockResolvedValue(status);
    render(SandboxStatus);
    await screen.findByText('Runner available');
    expect(screen.getByText('runner-container')).toBeTruthy();
    expect(screen.getByText('Blocked')).toBeTruthy();
    expect(screen.getByText('python, shell')).toBeTruthy();
    expect(screen.getByText('128 MiB / 64')).toBeTruthy();
    await fireEvent.click(screen.getByRole('button', { name: 'Refresh sandbox status' }));
    await waitFor(() => expect(api.getSandboxStatus).toHaveBeenCalledTimes(2));
  });

  it('shows a bounded unavailable state', async () => {
    api.getSandboxStatus.mockRejectedValue(new Error('Sandbox status unavailable (503)'));
    render(SandboxStatus);
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('Sandbox status unavailable (503)');
  });
});
