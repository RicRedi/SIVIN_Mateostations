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

## Follow-up after review

Changes after review round 1 (APPROVE, `5b75004`):

- `CopyButton.ts` (minor, accessible name): while the result is shown, the button's `aria-label`
  is set to the shown text (*Zkopírováno* / *Označeno – zkopírujte ručně*), so the accessible name
  matches the visible text; after the 2 s it returns to *Kopírovat polohu do schránky*. The
  live-region announcement is kept. Tests assert the label in the success, reset and fallback
  states.
- `styles.css` (minor): the button border uses `--line-strong` like the other controls; hover
  darkens it to `--ink-muted` (it was `--line-strong` before, which is now the resting colour).
- `position.test.ts` (nit): the locale test asserts the exact string `48.500000, 16.250000`.
- Card jump at 320 px with the fallback text (nit): **not changed**. Tried `white-space: nowrap` +
  `text-overflow: ellipsis` with `max-width: 100%` (which also needs `min-width: 0` on the metadata
  `dd`). It removed the jump, but at 320 px the button then read *Označeno – zko…*. That hides the
  instruction, which is worse than the 13 px jump, so it was reverted. Making the text shorter
  would drop "copy manually". At 390 px the fallback text fits on one line and the card height
  does not change (checked with Playwright: 227 px before and after).
- Late-timer nit left as is, as asked.

Gates after the follow-up (in `web/`): `npm run lint` → no findings; `npm run typecheck` → no
errors; `npm test` → 22 files, 234 tests passed, all files 99.62 % lines; `domain/position.ts` and
`ui/CopyButton.ts` 100 % lines and branches, `ui/SensorPanel.ts` 100 % lines / 88.88 % branches
(unchanged); `npm run build` → built, no warnings.

## Review

Verdict: APPROVE (round 1)

Reviewer: independent reviewer agent, 2026-10-15. Reviewed `git diff origin/main...HEAD` (4 commits,
`6bf23cd`..`85c4f2f`) against the owner-approved WP-3.6 brief.

### Gates observed (run by the reviewer in `web/`)

- `npm run lint` → no findings.
- `npm run typecheck` → no errors.
- `npm test` → 22 files, 234 tests passed; all files 99.62 % lines; `ui/SensorPanel.ts` 100 % lines,
  88.88 % branches (uncovered lines 89 and 126 are pre-existing); `domain/position.ts` and
  `ui/CopyButton.ts` not listed among files with uncovered lines (100 %).
- `npm run build` → built, no warnings.
- Scope: every changed path is under `web/src`, `web/tests`, `docs/web.md` or `docs/wp_log/`;
  no Python, workflow, plan or data change. Screenshots are 20–24 kB each.

### Independent checks (throwaway Playwright scripts outside the repo, `vite preview` of the build)

- Sensors 77678271 + 77680921 at 1280, 390 (`cs-CZ`) and 320 px (`de-DE` browser locale):
  document `scrollWidth` equals the viewport, no card overflows, the button stays inside the card.
- Coordinates read `48.880215, 16.673002` / `48.879593, 16.672016`, matching
  `public/data/sensors.geojson`; with `lang=en` and browser locale `de-DE` still a decimal point.
- Click → clipboard read back as `48.880215, 16.673002`, first button *Zkopírováno*, second still
  *Kopírovat*, live region *Zkopírováno*. A click followed immediately by a re-render (hash change
  to `lang=en`, `w=7d`) → no page error; buttons back to *Copy*.
- `writeText` patched to reject → coordinate text selected, fallback text shown, no error.
- Keyboard: Tab reaches the button, the global `:focus-visible` outline (3 px solid) applies,
  Enter triggers the copy.
- Not verified: real phone, Safari/iOS selection behaviour, actual screen reader (same limits as
  the hand-off note).

### Findings

| Severity | File:line | Finding | Status |
|---|---|---|---|
| minor | web/src/ui/CopyButton.ts:54 | Fixed `aria-label` makes the accessible name differ from the visible text during feedback | open |
| minor | web/src/styles.css:551 | Button border uses `--line` (#e1e0d9, about 1.3:1 on white) while other controls use `--line-strong` | open |
| nit | web/src/styles.css:548 | Fallback text wraps the button to two lines at 320 px (height 28 → 41 px), a layout jump | open |
| nit | web/src/ui/CopyButton.ts:61 | Clipboard promise resolving after a re-render schedules a timer on a disposed, detached button | open |
| nit | web/tests/position.test.ts:20 | The locale test (`not.toContain(',5')`) cannot fail for `toFixed`; it documents rather than tests | open |

Details:

1. **Accessible name (minor).** Input: click *Kopírovat*. Behaviour: the visible text becomes
   *Zkopírováno* / *Označeno – zkopírujte ručně*, but the accessible name stays "Kopírovat polohu
   do schránky" (WCAG 2.5.3 label-in-name is not met while feedback is shown; voice-control users
   saying the visible word miss). The live region does announce the result, so screen-reader users
   are informed. Suggested fix: drop `aria-label` and give the button visible text plus a
   visually hidden suffix (e.g. `<span class="visually-hidden"> polohu do schránky</span>`), or
   accept as is — the hand-off note already names it.
2. **Border contrast (minor).** The copy button is the only bordered control in the panel that uses
   `--line`; picker toggle, search and panel use `--line-strong`. Its boundary is hard to see on
   white. The visible text keeps it identifiable, so not a WCAG 1.4.11 failure, but it is less
   consistent with existing controls than the brief asks. Suggested fix: `border-color:
   var(--line-strong)` and a darker hover (e.g. `--ink-secondary`).
3. **Layout jump (nit).** At 320 px with the Czech fallback text the button grows to two lines and
   pushes *Poslední hodnoty* down for 2 s. Harmless; a shorter fallback text would avoid it.
4. **Late resolution (nit, by code reading).** `SensorPanel.render` disposes the buttons, but a
   `writeText` still pending then calls `showFeedback`, which starts a fresh timer on the detached
   button (and in the fallback path selects text that is no longer in the document). The
   `isConnected` guard makes the timer a no-op, and the Playwright click-then-re-render run showed no
   error, so it does not throw. Fix if desired: a `disposed` flag checked after the `await`.
5. **Locale test (nit).** `toFixed` ignores the locale by specification, and the assertion
   `not.toContain(',5')` would pass for almost any output. Suggested fix: assert the exact string
   (`'48.500000, 16.250000'`), as the other cases already do.

Formatting probed: `toFixed(6)` rounds the binary value (same as the registry precision), latitude
first, `", "` separator, negative zero normalised. `'clipboard' in navigator` is correct for
insecure contexts (the property is `[SecureContext]`). Per-card buttons and timers are independent
(test and browser). No `print`, no blanket ignores, constants named (`COPY_FEEDBACK_MS`,
`POSITION_DECIMALS`). `console.warn` in `CopyButton.selectSource` is a direct console use rather
than an injected logger; acceptable for a UI component, noted only.

### Deviations assessment

- **Row placement** after *Odrůda*: satisfies the brief literally ("after track, before latest
  values"); the open question to the owner is the right handling. Accepted.
- **New required constructor parameter `clipboard`**: proper dependency injection; `main.ts` is the
  only place touching `navigator`. Accepted.
- **No dark variant**: verified `color-scheme: light` only in `styles.css`; nothing to match.
  Accepted.
- Out-of-scope notes (docs tree, `screenshot.mjs`) are correctly left out.
