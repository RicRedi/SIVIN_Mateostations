type Attributes = Readonly<Record<string, string | number | boolean | undefined>>;
type Child = Node | string | null | undefined | false;

/**
 * Create an element with attributes and children. `true` sets a boolean attribute, `false` or
 * `undefined` omits it; `class` sets `className`.
 */
export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attributes: Attributes = {},
  children: readonly Child[] = [],
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (value === undefined || value === false) {
      continue;
    }
    element.setAttribute(name, value === true ? '' : String(value));
  }
  for (const child of children) {
    if (child !== null && child !== undefined && child !== false) {
      element.append(child);
    }
  }
  return element;
}
