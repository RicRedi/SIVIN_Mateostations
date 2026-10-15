// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { COPY_FEEDBACK_MS, CopyButton, type TextClipboard } from '../../src/ui/CopyButton';

const TEXT = '48.880215, 16.673002';
const LABELS = { idle: 'Kopírovat', action: 'Kopírovat polohu do schránky', copied: 'Zkopírováno', selected: 'Označeno' };

function mount(clipboard: TextClipboard | null): { copy: CopyButton; source: HTMLElement } {
  const source = document.createElement('span');
  source.textContent = TEXT;
  const copy = new CopyButton(TEXT, source, clipboard, LABELS);
  document.body.replaceChildren(source, copy.button, copy.announcer);
  return { copy, source };
}

/** Click and let the clipboard promise settle. */
async function click(copy: CopyButton): Promise<void> {
  copy.button.click();
  await vi.advanceTimersByTimeAsync(0);
}

describe('CopyButton', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    document.getSelection()?.removeAllRanges();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('is an accessible button with the idle text', () => {
    const { copy } = mount(null);
    expect(copy.button.type).toBe('button');
    expect(copy.button.getAttribute('aria-label')).toBe('Kopírovat polohu do schránky');
    expect(copy.button.textContent).toBe('Kopírovat');
    expect(copy.announcer.getAttribute('aria-live')).toBe('polite');
    expect(COPY_FEEDBACK_MS).toBe(2000);
  });

  it('copies the exact text and shows "copied" for two seconds', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    const { copy } = mount({ writeText });
    await click(copy);
    expect(writeText).toHaveBeenCalledWith(TEXT);
    expect(copy.button.textContent).toBe('Zkopírováno');
    expect(copy.announcer.textContent).toBe('Zkopírováno');
    await vi.advanceTimersByTimeAsync(COPY_FEEDBACK_MS - 1);
    expect(copy.button.textContent).toBe('Zkopírováno');
    await vi.advanceTimersByTimeAsync(1);
    expect(copy.button.textContent).toBe('Kopírovat');
    expect(copy.announcer.textContent).toBe('');
    expect(copy.button.disabled).toBe(false);
  });

  it('restarts the timer on a repeated click', async () => {
    const { copy } = mount({ writeText: () => Promise.resolve() });
    await click(copy);
    await vi.advanceTimersByTimeAsync(1500);
    await click(copy);
    await vi.advanceTimersByTimeAsync(1500);
    expect(copy.button.textContent).toBe('Zkopírováno');
    await vi.advanceTimersByTimeAsync(500);
    expect(copy.button.textContent).toBe('Kopírovat');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('selects the text for a manual copy when writing is rejected', async () => {
    const { copy } = mount({ writeText: () => Promise.reject(new Error('NotAllowedError')) });
    await click(copy);
    expect(document.getSelection()?.toString()).toBe(TEXT);
    expect(copy.button.textContent).toBe('Označeno');
    await vi.advanceTimersByTimeAsync(COPY_FEEDBACK_MS);
    expect(copy.button.textContent).toBe('Kopírovat');
  });

  it('falls back when writeText throws synchronously', async () => {
    const { copy } = mount({
      writeText: () => {
        throw new Error('sync');
      },
    });
    await click(copy);
    expect(document.getSelection()?.toString()).toBe(TEXT);
    expect(copy.button.textContent).toBe('Označeno');
  });

  it('falls back when the Clipboard API is missing', async () => {
    const { copy } = mount(null);
    await click(copy);
    expect(document.getSelection()?.toString()).toBe(TEXT);
    expect(copy.button.textContent).toBe('Označeno');
  });

  it('never throws when the selection is unavailable or fails', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { copy } = mount(null);
    vi.spyOn(document, 'getSelection').mockReturnValue(null);
    await expect(copy.copy()).resolves.toBeUndefined();
    vi.spyOn(document, 'getSelection').mockRestore();
    vi.spyOn(document, 'createRange').mockImplementation(() => {
      throw new Error('no range');
    });
    await expect(copy.copy()).resolves.toBeUndefined();
    expect(warn).toHaveBeenCalledOnce();
    expect(copy.button.textContent).toBe('Označeno');
  });

  it('leaves a detached button alone when its timer fires', async () => {
    const { copy } = mount({ writeText: () => Promise.resolve() });
    await click(copy);
    copy.button.remove();
    await vi.advanceTimersByTimeAsync(COPY_FEEDBACK_MS);
    expect(copy.button.textContent).toBe('Zkopírováno');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cancels a pending reset on dispose', async () => {
    const { copy } = mount({ writeText: () => Promise.resolve() });
    await click(copy);
    expect(vi.getTimerCount()).toBe(1);
    copy.dispose();
    expect(vi.getTimerCount()).toBe(0);
  });
});
