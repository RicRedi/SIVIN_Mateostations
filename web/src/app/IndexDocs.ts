/**
 * Links from an index to its documentation page on GitHub ("Jak se počítá"). The manifest gives
 * each index a repository path (`doc`, e.g. `docs/indices/huglin.md`); this class turns it into
 * a URL under one configurable base, so the repository location is defined in one place.
 */
export class IndexDocs {
  /**
   * @param baseUrl - URL of the repository's files on the default branch, ending with `/`
   *   (e.g. `https://github.com/<owner>/<repo>/blob/main/`).
   */
  constructor(private readonly baseUrl: string) {
    if (!baseUrl.endsWith('/')) {
      throw new RangeError(`Documentation base URL must end with "/", got "${baseUrl}"`);
    }
  }

  /** URL of the documentation page at repository path `doc` (a leading `/` is ignored). */
  url(doc: string): string {
    return `${this.baseUrl}${doc.replace(/^\/+/, '')}`;
  }
}
