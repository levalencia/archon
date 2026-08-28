import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ChatInput from './ChatInput.svelte';

afterEach(cleanup);

describe('ChatInput image contract', () => {
  it('sends the complete bounded image Data URI', async () => {
    const onSend = vi.fn();
    const { container } = render(ChatInput, { props: { onSend } });
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File([new Uint8Array([137, 80, 78, 71])], 'tiny.png', {
      type: 'image/png',
    });
    Object.defineProperty(input, 'files', { configurable: true, value: [file] });
    await fireEvent.change(input);
    await waitFor(() => expect(screen.getByAltText('Selected upload')).toBeTruthy());
    await fireEvent.click(screen.getByRole('button', { name: 'Send' }));
    expect(onSend).toHaveBeenCalledWith(
      'Describe this image',
      expect.stringMatching(/^data:image\/png;base64,/),
    );
  });
});
