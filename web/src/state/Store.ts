/** Called after the state changed, with the new and the previous state. */
export type Listener<T> = (state: T, previous: T) => void;

/**
 * A minimal observable store holding one immutable state object.
 *
 * `update` replaces the state with a shallow-merged copy and notifies listeners only when at
 * least one top-level field changed (compared with `Object.is`). Notification is not
 * re-entrant: an `update` made by a listener is applied at once (so `state` is always current)
 * but its notification is queued until every listener has seen the previous change. Listeners
 * therefore receive changes in order and never an outdated state after a newer one. If a
 * listener throws, the remaining listeners and queued changes are still delivered and the first
 * error is rethrown afterwards.
 */
export class Store<T extends object> {
  private current: T;
  private readonly listeners = new Set<Listener<T>>();
  private readonly queue: (readonly [T, T])[] = [];
  private notifying = false;

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
    this.queue.push([next, previous]);
    this.flush();
  }

  /** @returns A function that removes the listener. */
  subscribe(listener: Listener<T>): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private flush(): void {
    if (this.notifying) {
      return;
    }
    this.notifying = true;
    const errors: unknown[] = [];
    try {
      for (let change = this.queue.shift(); change !== undefined; change = this.queue.shift()) {
        const [next, previous] = change;
        for (const listener of this.listeners) {
          try {
            listener(next, previous);
          } catch (error) {
            errors.push(error);
          }
        }
      }
    } finally {
      this.notifying = false;
    }
    if (errors.length > 0) {
      throw errors[0];
    }
  }
}
