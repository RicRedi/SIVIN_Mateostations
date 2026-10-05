# Real export (REAL DATA, not synthetic)

`MeteoData_8615620_77799986_VUT_20260301_223842.csv` is an excerpt of a **real export** of
sensor `77799986` downloaded from the data provider's portal (export time stamp
2026-03-01 22:38:42 local). The values are real measurements. The data are **public by owner
decision 2026-10-05** (MIGRATION_PLAN §0.5); the owner supplied the file as the answer to
question Q1 (§0.6.1).

## Provenance and trimming

- Source: the full export, 3520 data rows, 2025-07-30 10:22:29 to 2026-03-01 22:27:05 local
  time (2025-07-30 08:22:29Z to 2026-03-01 21:27:05Z), newest row first, 165 551 bytes.
- Trimmed by the WP-0.2 worker (Claude, 2026-10-05) to 300 data rows. The rows are copied
  byte for byte and not edited, reordered or invented:
  - the **150 newest** rows (file lines 3–152 of the original, 2026-03-01 22:27:05 back to
    2026-02-26 18:44:46 local),
  - the **150 oldest** rows (file lines 3373–3522 of the original, 2025-12-20 12:29:47 back to
    2025-07-30 10:22:29 local). They contain the transition of 2025-12-17/18 and the oldest
    rows of 2025-07-30/31 with the gaps of 3.5 h, 23.4 h and 139 days (3336.6 h) before
    2025-12-17 12:58:06 local.
- Kept exactly: the title line `Meteo Data;`, the header line with all six columns
  (`Datum a čas;Teplota (°C);Vlhkost (%);Srážky (mm);Celkové srážky (mm);Nabití baterie (V)`),
  the trailing line `;`, UTF-8 without BOM, CRLF line endings.
- The cut between the two blocks creates a gap of 1638.25 h (2025-12-20 → 2026-02-26) that is
  **not** in the original file.
- The original file has no daylight-saving transition inside the data: the autumn 2025
  fall-back lies in the 139-day gap and the 2026 spring-forward (2026-03-29) is after the
  export. None was added.

Context (owner question Q10, MIGRATION_PLAN §0.6): from 2025-12-17 the values look like indoor
conditions (18–24 °C, RH about 30 %). The excerpt is used for format regression tests, not for
indices.

Test: `tests/ingest/test_real_export.py`.
