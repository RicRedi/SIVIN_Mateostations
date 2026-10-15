import { el } from './dom';

/**
 * How long the button shows the result of a copy before it returns to its idle text, in ms.
 * Owner's design (WP-3.6): two seconds.
 */
export const COPY_FEEDBACK_MS = 2000;

/** The part of the asynchronous Clipboard API the button needs (`navigator.clipboard`). */
export interface TextClipboard {
  writeText(text: string): Promise<void>;
}

/** Texts of a {@link CopyButton}, already translated. */
export interface CopyButtonLabels {
  /** Visible text while idle, e.g. "Kopírovat". */
  readonly idle: string;
  /** Accessible name of the button, e.g. "Kopírovat polohu do schránky". */
  readonly action: string;
  /** Shown after a successful copy, e.g. "Zkopírováno". */
  readonly copied: string;
  /** Shown when the text was only selected for a manual copy. */
  readonly selected: string;
}

/**
 * A button that copies a fixed text to the clipboard.
 *
 * On success the button shows `labels.copied` for `feedbackMs`; when the clipboard is unavailable
 * or refuses, it selects the text of `source` so the user can copy it by hand and shows
 * `labels.selected` for the same time. A repeated click restarts the timer. While the result is
 * shown, it is also the button's accessible name, and it is written to a polite live region for
 * screen readers. Copying never throws.
 */
export class CopyButton {
  readonly button: HTMLButtonElement;
  /** Visually hidden `aria-live` region announcing the result; place it next to the button. */
  readonly announcer = el('span', { class: 'visually-hidden', 'aria-live': 'polite' });
  private timer: ReturnType<typeof setTimeout> | null = null;

  /**
   * @param text - Exact text to copy.
   * @param source - Element showing `text`; selected when copying is not possible.
   * @param clipboard - The clipboard, or `null` where the API is missing (insecure context).
   * @param labels - Translated texts.
   * @param feedbackMs - Duration of the result feedback, ms.
   */
  constructor(
    private readonly text: string,
    private readonly source: HTMLElement,
    private readonly clipboard: TextClipboard | null,
    private readonly labels: CopyButtonLabels,
    private readonly feedbackMs: number = COPY_FEEDBACK_MS,
  ) {
    this.button = el('button', { type: 'button', class: 'copy-button', 'aria-label': labels.action }, [labels.idle]);
    this.button.addEventListener('click', () => {
      void this.copy();
    });
  }

  /** Copy the text (or select it as a fallback) and show the result. */
  async copy(): Promise<void> {
    let copied = false;
    if (this.clipboard !== null) {
      try {
        await this.clipboard.writeText(this.text);
        copied = true;
      } catch {
        copied = false;
      }
    }
    if (!copied) {
      this.selectSource();
    }
    this.showFeedback(copied ? this.labels.copied : this.labels.selected);
  }

  /** Cancel a pending reset, e.g. when the button is removed from the page. */
  dispose(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }

  private showFeedback(message: string): void {
    this.dispose();
    this.button.textContent = message;
    this.button.setAttribute('aria-label', message);
    this.announcer.textContent = message;
    this.timer = setTimeout(() => {
      this.timer = null;
      if (this.button.isConnected) {
        this.button.textContent = this.labels.idle;
        this.button.setAttribute('aria-label', this.labels.action);
        this.announcer.textContent = '';
      }
    }, this.feedbackMs);
  }

  private selectSource(): void {
    const document = this.source.ownerDocument;
    const selection = document.getSelection();
    if (selection === null) {
      return;
    }
    try {
      const range = document.createRange();
      range.selectNodeContents(this.source);
      selection.removeAllRanges();
      selection.addRange(range);
    } catch (error) {
      console.warn('Could not select the text for a manual copy', error);
    }
  }
}
