/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** `"false"` hides the synthetic-data badge; any other value (or unset) shows it. */
  readonly VITE_DEMO_DATA?: string;
  /** Base URL of the repository files for the "how it is computed" links (ends with `/`). */
  readonly VITE_DOCS_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
