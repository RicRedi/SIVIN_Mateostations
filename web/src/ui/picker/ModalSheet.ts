/** Focusable controls of a sheet, for the focus trap. */
const FOCUSABLE = 'input, button, select, textarea, a[href], [tabindex]:not([tabindex="-1"])';

/**
 * Makes an open panel a modal dialog (the full-screen sheet on phones): `role="dialog"` with
 * `aria-modal="true"`, the rest of the page `inert` (not focusable, hidden from assistive
 * technology), and Tab / Shift+Tab wrap around inside the sheet.
 *
 * `inert` is set on every sibling of the panel and of each of its ancestors up to `<body>`, and
 * removed again on {@link deactivate}; elements that were inert already are left alone.
 */
export class ModalSheet {
  private inerted: Element[] = [];
  private isActive = false;

  /** @param panel - The sheet element; its role is restored to `restRole` on deactivation. */
  constructor(
    private readonly panel: HTMLElement,
    private readonly restRole: string,
  ) {}

  get active(): boolean {
    return this.isActive;
  }

  activate(): void {
    this.isActive = true;
    this.panel.setAttribute('role', 'dialog');
    this.panel.setAttribute('aria-modal', 'true');
    for (let node: Element = this.panel; node.parentElement !== null && node !== node.ownerDocument.body; node = node.parentElement) {
      for (const sibling of node.parentElement.children) {
        if (sibling !== node && !sibling.hasAttribute('inert')) {
          sibling.setAttribute('inert', '');
          this.inerted.push(sibling);
        }
      }
    }
  }

  deactivate(): void {
    this.isActive = false;
    this.panel.setAttribute('role', this.restRole);
    this.panel.removeAttribute('aria-modal');
    for (const element of this.inerted) {
      element.removeAttribute('inert');
    }
    this.inerted = [];
  }

  /** Keep Tab inside the sheet: wrap from the last control to the first and back. */
  trapTab(event: KeyboardEvent): void {
    if (!this.isActive || event.key !== 'Tab') {
      return;
    }
    const controls = [...this.panel.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((c) => c.closest('[hidden]') === null);
    const first = controls[0];
    const last = controls.at(-1);
    const active = this.panel.ownerDocument.activeElement;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first?.focus();
    }
  }
}
