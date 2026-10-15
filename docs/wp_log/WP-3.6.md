# WP-3.6 — Copy sensor position to the clipboard

## Summary

Small web-only change requested by the owner on 2026-10-15 (not yet in MIGRATION_PLAN §4). Each
sensor card gets a *Poloha* row with the sensor's current position as selectable text,
`"<lat>, <lon>"` with exactly six decimals and a decimal point in every UI language, and a
*Kopírovat* button. The button writes exactly that text with `navigator.clipboard.writeText`,
shows *Zkopírováno* for 2 s (`COPY_FEEDBACK_MS`, a repeated click restarts the timer) and announces
the result in a polite live region. When the Clipboard API is missing or the write is refused, it
selects the coordinate text for a manual copy and shows *Označeno – zkopírujte ručně* for the same
time; copying never throws. Every card has its own button and timer; `SensorPanel` cancels the
timers of replaced cards on re-render, and a timer firing on a detached button does nothing. No
navigation link (declined by the owner).

## Changed files

Branch `wp/3.6-copy-position`, base `bdf44c3` (`main`).

| Commit | Content |
|---|---|
| `6bf23cd` | `web/src/domain/position.ts` (new: `formatPosition`, `POSITION_DECIMALS`), `web/tests/position.test.ts` (new) |
| `dccda5b` | `web/src/ui/CopyButton.ts` (new: `CopyButton`, `TextClipboard`, `CopyButtonLabels`, `COPY_FEEDBACK_MS`), `web/tests/ui/CopyButton.test.ts` (new) |
| `66e1f6d` | `web/src/ui/SensorPanel.ts` (position row, new constructor parameter `clipboard: TextClipboard \| null`, disposal of old buttons), `web/src/main.ts` (injects `navigator.clipboard` or `null`), `web/src/i18n/{cs,de,en}.ts` (5 keys: `position`, `copyPosition`, `copyPositionLabel`, `positionCopied`, `positionSelected`), `web/src/styles.css` (`.sensor-card__position`, `.sensor-card__coords`, `.copy-button`), `web/tests/ui/components.test.ts` (existing panel tests pass `null`; new `SensorPanel position row` block) |
| (this commit) | `docs/web.md` (one paragraph *Copying a sensor position*), `docs/wp_log/WP-3.6.md`, `docs/wp_log/img/WP-3.6-*.png` |

Design: the formatting is a pure domain function (no `I18n`, deliberately not
`Intl.NumberFormat`; `toFixed(6)`, a rounded negative zero is written as `0.000000`). The clipboard
is a collaborator injected through the constructor (`TextClipboard`, the one method of the
Clipboard API used), so `main.ts` stays the only place touching `navigator` and tests pass fakes.

## How it was verified

Run in `/home/user/wt/wp-3.6/web`:

- `npm run lint` → no findings.
- `npm run typecheck` → no errors.
- `npm test` → 22 test files, 234 tests passed; overall line coverage 99.62 % (threshold 85 %).
- Coverage of changed files (V8, json-summary): `domain/position.ts`, `ui/CopyButton.ts`,
  `i18n/{cs,de,en}.ts` 100 % lines/branches/functions; `ui/SensorPanel.ts` 100 % lines, 88.88 %
  branches (the two uncovered branches, lines 89 and 126, are pre-existing and not touched here).
- `npm run build` → built, no warnings.
- Tests cover: formatting (6 decimals, point, latitude first, negative numbers, rounding
  48.8802154 → 48.880215 and 16.6730026 → 16.673003, negative zero); copy success → *Zkopírováno*
  and back after exactly 2 s (fake timers); repeated click restarts the timer; rejection and a
  synchronously throwing `writeText` → fallback text and the coordinate text selected; missing API
  (`null`) → fallback; `getSelection()` returning `null` or `createRange` throwing → no throw (one
  `console.warn`); detached button; `dispose`; two cards with independent buttons and timers;
  re-render cancels pending timers; row present as the last metadata row, before the latest values,
  with the committed fixture values of sensor 77678271 (`48.880215, 16.673002`); English labels.
- Visual check: `vite preview` of the build, Playwright with the preinstalled Chromium
  (throwaway script in the session scratchpad, not committed), comparison of 77678271 and
  77680921, `lang=cs`:
  - `img/WP-3.6-desktop-before.png`, `img/WP-3.6-desktop-after.png` (1280 px),
    `img/WP-3.6-phone-before.png`, `img/WP-3.6-phone-after.png` (390 px): element screenshots of
    the first card. After the click the clipboard read back as `48.880215, 16.673002`, the second
    card's button still showed *Kopírovat*, and 2.1 s later the first button was back at
    *Kopírovat*.
  - `img/WP-3.6-phone-fallback.png` (390 px): `navigator.clipboard.writeText` replaced by a
    rejecting stub; the coordinate text is selected and the button shows the fallback text.
  - Document `scrollWidth` equalled the viewport width (1280 / 390 px) and no card overflowed
    horizontally; the button stays inside the card.

## What did not work / what was not verified

- Not tested on a real phone or in Safari/Firefox; only headless Chromium and jsdom. In
  particular the iOS behaviour of the programmatic selection fallback is not verified.
- The screen-reader announcement (live region) was checked only as DOM state, not with an actual
  screen reader.
- In the narrow desktop comparison card (two cards side by side) the coordinate text wraps at the
  space after the comma and the button goes to the next line (see `WP-3.6-desktop-*.png`). The
  copied text is unaffected. On the phone the coordinates fit on one line and the button wraps
  below them.
- While feedback is shown, the button's accessible name stays "Kopírovat polohu do schránky"
  (from `aria-label`) and does not contain the visible text *Zkopírováno*; the result reaches
  screen readers through the live region instead.

## Deviations

- Row placement: the brief says "after *Viniční trať* and before the latest values". The row is
  the last metadata row, i.e. after the track **and** after the variety (when present), directly
  above *Poslední hodnoty*. This satisfies both conditions literally; if the owner wants it
  directly below the track (above the variety), it is a one-line move in `SensorPanel.card`.
- `SensorPanel` takes a new required constructor parameter `clipboard`; `main.ts` and the four
  existing panel tests were updated accordingly.
- The site has no dark theme (`color-scheme: light` only), so there is no dark variant to match;
  the button uses the existing tokens (`--line`, `--line-strong`, `--ink-secondary`, `--radius`)
  and the same white background as the card.

## Out of scope

- `docs/web.md` architecture tree and class table do not list `ui/CopyButton` and
  `domain/position`; only the requested paragraph was added. Worth adding when the doc is next
  touched.
- `web/scripts/screenshot.mjs` was not extended with the WP-3.6 shots (outside the Files scope);
  the screenshots were taken with a throwaway script.

## Open questions for the owner

- Placement of the row (see *Deviations*): last metadata row (as built) or directly below the
  track?

## Review

Verdict: _pending_
| Severity | File:line | Finding | Status |
|---|---|---|---|
