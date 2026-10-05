/** Called after the state changed, with the new and the previous state. */
export type Listener<T> = (state: T, previous: T) => void;

/**
 * A minimal observable store holding one immutable state object.
 *
 * `update` replaces the state with a shallow-merged copy and notifies listeners only when at
 * least one top-level field changed (compared with `Object.is`).
 */
export class Store<T extends object> {
  private current: T;
  private readonly listeners = new Set<Listener<T>>();

  constructor(initial: T) {
    this.current = Object.freeze({ ...initial });
  }

  get state(): T {
    return this.current;
  }

  update(patch: Partial<T>): void {
    const previous = this.current;
    const next = Object.freeze({ ...previous, ...patch });
    const changed = (Object.keys(patch) as (keyof T)[]).some(
      (key) => !Object.is(previous[key], next[key]),
    );
    if (!changed) {
      return;
    }
    this.current = next;
    for (const listener of this.listeners) {
      listener(next, previous);
    }
  }

  /** @returns A function that removes the listener. */
  subscribe(listener: Listener<T>): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
