/** Raised when a contract file cannot be fetched or parsed as JSON. */
export class DataLoadError extends Error {
  /**
   * @param url - URL that failed.
   * @param reason - Human-readable cause, e.g. `HTTP 404`.
   */
  constructor(
    readonly url: string,
    readonly reason: string,
  ) {
    super(`Cannot load ${url}: ${reason}`);
    this.name = 'DataLoadError';
  }
}
