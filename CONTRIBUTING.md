# Contributing

A summary of the engineering standards. The binding text is
**[MIGRATION_PLAN.md §1](MIGRATION_PLAN.md#1-inženýrské-standardy)** — this file is a shortcut to
it, not a second source of truth. If the two disagree, the plan is right and this file is stale,
so say so.

---

## Developer setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev,ingest,viz]"   # after WP-0.1; before it only requirements.txt exists
.venv/bin/pre-commit install                    # optional; CI runs the same checks

cd web && npm ci                                # frontend (Node 22)
```

Credentials for the data provider are read from the environment (`SIVIN_USER`,
`SIVIN_PASSWORD`). Locally put them into `.env` (git-ignored). Never commit them.

## Before you propose a change

```bash
make lint type test     # ruff check + format --check, mypy --strict, pytest
make cov                # coverage, term-missing
cd web && npm run lint && npm run typecheck && npm test && npm run build
```

Run them **in your own worktree**, before pushing. CI runs the same gates.

## Code

| Topic | Rule |
|---|---|
| Language | Code, comments, docstrings, `docs/` and commit messages in **English**. |
| Python | 3.12, `src/` layout, package `sivin`. |
| Style | `ruff check` + `ruff format`, line length 100. |
| Typing | Full annotations in `src/`; `mypy --strict` must pass. Web: TypeScript `strict`. |
| Docstrings | NumPy style. Every public class and function documents parameters, returns and **units**. |
| Naming | `snake_case` functions/variables, `PascalCase` classes, `UPPER_SNAKE` constants, `_private` helpers. |
| Units in names | `temp_c`, `rh_pct`, `vpd_kpa`, `duration_s`, `elevation_m`. Internally all timestamps are **UTC**. |
| Magic numbers | None. Thresholds come from config or a named constant whose comment cites the source. |
| Logging | `logger = logging.getLogger(__name__)` per module; logging is configured only in `cli.py`; no `print` in `src/`. |
| Dead code | No commented-out code, no ASCII-art headers, no authorship banners in source files. |

**Design, in one line each:** domain concepts are classes; extension points are `ABC`s or
`Protocol`s; new behaviour is **a new class that registers itself**, never a new `if/elif` branch;
collaborators arrive through the constructor and factories build them from config; value objects
are frozen; no singletons, no module-level mutable state, **no work at import time**; small pure
math lives in functions tested in isolation. Full text:
[MIGRATION_PLAN.md §1.2](MIGRATION_PLAN.md#12-objektový-návrh-a-čitelnost).

## Configuration

One file, `config/sivin.yaml`. Every section is a frozen pydantic v2 model with `extra="forbid"`,
so a typo in a key fails at start-up with the key path. Paths are relative to the project root and
resolved by `ProjectPaths` — **no absolute user path is ever committed**. Secrets come only from
the environment. Every field has a description and a unit.

## Data contracts

The canonical measurement schema, the sensor registry and the static site data contract are
defined in [MIGRATION_PLAN.md §2](MIGRATION_PLAN.md#2-cílová-architektura-a-kontrakty). They are
frozen: changing one is a plan change approved by the owner, not part of a workpackage.

## Tests

- Unit tests compare against **hand-computed** values, not against what the code currently prints.
- Every climate index has a small hand-computable test case and a `docs/indices/<id>.md` page.
- Fixtures are synthetic, deterministic (explicit seed) and labelled as synthetic.
- No test touches the network or the data provider's portal; use mocks and saved HTML.
- Coverage of code a workpackage adds or changes: **≥ 85 %** (`cli.py` and plotting exempt).

## Documentation

`docs/` is permanent. Each index gets `docs/indices/<id>.md` with purpose, formula (LaTeX),
period, parameters, interpretation, limitations for our data, implementation and references.
**Never invent a citation or a DOI**; mark an unverified DOI as `[DOI not verified]`.

## Workpackages, branches and merges

One workpackage = one branch = one worktree. Branch names are `wp/<id>-<slug>`, e.g.
`wp/1.5-quality-control`. Commits are conventional and carry the workpackage id:

```
feat(quality): detect office-to-field deployment step [WP-1.5]
```

**Stay inside the workpackage's `Files` scope.** Anything else that should be fixed goes into the
hand-off note under *Out of scope*.

**Only the owner merges.** Nobody else pushes to `main` or merges a branch. Rebase while a branch is
unpushed; once pushed, `git merge origin/main` instead — rewriting history breaks other checkouts.

## Definition of Done

Full checklist: [MIGRATION_PLAN.md §1.8](MIGRATION_PLAN.md#18-definition-of-done-každý-wp).

- [ ] Acceptance criteria of the workpackage met.
- [ ] `make lint type test` (and web gates, if touched) green in this worktree.
- [ ] Coverage of changed code ≥ 85 %.
- [ ] Nothing outside the `Files` scope changed.
- [ ] Every new config field has a description and a unit.
- [ ] Every new index has its `docs/indices/<id>.md`.
- [ ] Hand-off note `docs/wp_log/WP-<id>.md`, **including what did not work and what was not
      verified**.
- [ ] Review verdict `APPROVE`, or open findings explicitly handed to the owner.

## Reporting

Say what you did not verify. If a gate did not run, or something could not be checked against
real data or the real portal, write that down rather than leaving it to be assumed. Never present
an invented number as a measurement.
