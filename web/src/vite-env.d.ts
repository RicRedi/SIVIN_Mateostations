/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** `"false"` hides the synthetic-data badge; any other value (or unset) shows it. */
  readonly VITE_DEMO_DATA?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
