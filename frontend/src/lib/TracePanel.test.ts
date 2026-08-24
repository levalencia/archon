import { cleanup, fireEvent, render, screen } from '@testing-library/svelte';
import { afterEach, describe, expect, it } from 'vitest';
import TracePanel from './components/TracePanel.svelte';

afterEach(cleanup);

describe('TracePanel', () => {
  it('renders the default trace statistics', () => {
    render(TracePanel);

    expect(screen.getByText('Latency').nextElementSibling?.textContent).toBe('—');
    expect(screen.getByText('Tokens').nextElementSibling?.textContent).toBe('—');
    expect(screen.getByText('Tools').nextElementSibling?.textContent).toBe('0');
    expect(screen.getByText('Iterations').nextElementSibling?.textContent).toBe('0');
  });

  it('switches between trace panel tabs', async () => {
    render(TracePanel);

    await fireEvent.click(screen.getByRole('button', { name: 'audit' }));
    expect(screen.getByText('Audit log will show here')).toBeTruthy();
    expect(screen.queryByText('TRACE WATERFALL')).toBeNull();

    await fireEvent.click(screen.getByRole('button', { name: 'metrics' }));
    expect(screen.getByText('Metrics dashboard will show here')).toBeTruthy();
  });
});