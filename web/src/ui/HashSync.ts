import { DEFAULT_APP_STATE, type AppStore } from '../state/AppState';
import type { HashStateCodec } from '../state/HashStateCodec';

/**
 * Two-way binding between the store and `location.hash`: state changes replace the hash
 * (without adding history entries). A hash edited by the user replaces the state; fields it
 * omits return to their defaults, except the language, which stays.
 */
export class HashSync {
  constructor(
    private readonly store: AppStore,
    private readonly codec: HashStateCodec,
    private readonly location: Location,
    private readonly history: History,
    target: Window,
  ) {
    store.subscribe(() => {
      this.write();
    });
    target.addEventListener('hashchange', () => {
      const { language } = this.store.state;
      this.store.update({ ...DEFAULT_APP_STATE, language, ...this.codec.decode(this.location.hash) });
    });
  }

  /** Write the store's current state (never a notified snapshot, which may be outdated). */
  write(): void {
    const hash = this.codec.encode(this.store.state);
    if (hash !== this.location.hash) {
      this.history.replaceState(null, '', hash);
    }
  }
}
