/** The object-URL part of the `URL` API (injected, so tests need no real blob URLs). */
export interface ObjectUrls {
  createObjectURL(blob: Blob): string;
  revokeObjectURL(url: string): void;
}

/** MIME type of the CSV export. */
export const CSV_MIME_TYPE = 'text/csv;charset=utf-8';

/**
 * Delay before an object URL is revoked, ms: some browsers start the download only after the
 * click handler returned, so revoking at once can cancel it.
 */
export const REVOKE_DELAY_MS = 1000;

/** Saves text as a file in the browser: a Blob, an object URL and a temporary `<a download>`. */
export class FileDownload {
  constructor(
    private readonly document: Document,
    private readonly urls: ObjectUrls,
  ) {}

  /**
   * @param fileName - Suggested file name.
   * @param content - File content (already with a BOM where wanted).
   * @param mimeType - Content type of the Blob.
   */
  save(fileName: string, content: string, mimeType: string = CSV_MIME_TYPE): void {
    const url = this.urls.createObjectURL(new Blob([content], { type: mimeType }));
    const link = this.document.createElement('a');
    link.href = url;
    link.download = fileName;
    link.hidden = true;
    this.document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => {
      this.urls.revokeObjectURL(url);
    }, REVOKE_DELAY_MS);
  }
}
