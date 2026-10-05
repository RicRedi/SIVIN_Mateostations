# CLAUDE.md — SIVIN Meteostations

Pracovní pravidla pro Claude Code v tomto repozitáři. Platí pro interaktivní session
i pro subagenty (worker, reviewer).

## Vztah k ostatním souborům

- **Tento soubor říká, jak pracuju.** Prostředí, git, role, styl komunikace.
- **[MIGRATION_PLAN.md](MIGRATION_PLAN.md) říká, co se dělá.** Architektura, kontrakty (§2),
  workpackages (§4), rozhodnutí vlastníka (§0.5), otevřené otázky (§0.6).
- **[CONTRIBUTING.md](CONTRIBUTING.md)** je výtah inženýrských standardů (§1 plánu).
- Před prací si přečti `MIGRATION_PLAN.md` §0, §1, §2 a zadání svého WP v §4.
- Když si soubory odporují, platí plán. **Nevybírej si potichu** — zapiš otázku do hand-off note
  (sekce *Open questions for the owner*) a pokračuj tím, co rozporem dotčené není.

## Projekt

- Nástroj pro sběr, kontrolu, analýzu a zobrazení dat z meteostanic ve vinicích na jižní Moravě.
  Dnes 4 čidla (teplota, relativní vlhkost, krok ~1825 s), počet poroste.
- Zdroj dat: portál `lemon.e-service.cz` (DotVVM), **bez API** — export do Excelu přes
  automatizovaný prohlížeč.
- Cíl: Python balíček `sivin` + statický mapový portál na GitHub Pages, data jako soubory
  ve větvi `data`, bez databáze. Data jsou veřejná.
- **Drž se plánu.** Malá odbočka ano, rozšíření ne — patří do *Out of scope* nebo jako návrh ownerovi.

## Python prostředí

- Python **3.12**, virtuální prostředí `.venv` v kořeni repozitáře.
- Vytvoření: `python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev,ingest,viz]"`
  (před WP-0.1 existuje jen legacy `requirements.txt`).
- Každý bash příkaz běží v nové shellu, aktivace nepřetrvá. Spouštěj přes `.venv/bin/…`:
  `.venv/bin/python -m pytest -q`, nebo `make lint type test` (Makefile volá `.venv/bin`).
- Novou závislost přidej do `pyproject.toml` jen ve WP, který ji má ve scope; jinak ji uveď
  v hand-off note. Nic neinstaluj mimo definici prostředí.
- Web: Node 22, `npm ci` a skripty v `web/package.json`.

## Data a tajné údaje

- Měřená data nejsou ve `main`. Lokálně v `data/` (ignorováno), v produkci ve větvi `data`,
  kterou zapisuje jen workflow.
- **Nikdy nevydávej vymyšlená čísla za měření z čidel.** Fixtures jsou syntetické a jako takové
  označené. Když reálná data chybí, napiš to.
- **Nikdy nevymýšlej citace ani DOI.** Neověřené DOI označ `[DOI neověřeno]`.
- Přihlašovací údaje k portálu jen z prostředí (`SIVIN_USER`, `SIVIN_PASSWORD`), lokálně z `.env`,
  v Actions ze Secrets. Nikdy je nelogguj, necommituj ani nevypisuj.
- Na reálný portál se z agentního prostředí nepřipojuj. Testuje se proti mockům a uloženému HTML.

## Agentní tým

Role jsou definované v `MIGRATION_PLAN.md` §0.1, životní cyklus WP v §0.2.

- **Orchestrátor** (hlavní session): zakládá větve a worktree, zadává práci, znovu spouští gates,
  spouští reviewera, pushuje větve, reportuje ownerovi.
- **Worker:** jeden WP, jeden worktree, jen `Files` scope. Commituje, nepushuje.
- **Reviewer:** nezávislý na workerovi. Nález zapisuje do sekce *Review* v
  `docs/wp_log/WP-<id>.md`, kód sám neopravuje. Verdikt `APPROVE` / `CHANGES_REQUESTED`.
- **Owner (Richard):** rozhoduje, merguje, uzavírá.

## Git

- **Nikdy nepushuj do `main`, nikdy nemerguj a neotevírej PR**, pokud o to owner výslovně
  nepožádá. Merguje výhradně Richard.
- Jedna větev = jeden worktree = jeden WP. Název `wp/<id>-<slug>`, např. `wp/1.5-quality-control`.
  Worktree `../wt/wp-<id>`. Báze větve podle `MIGRATION_PLAN.md` §0.4.
- Commit: conventional commit v angličtině s ID WP, např.
  `feat(registry): add placement history to sensors [WP-1.1]`.
- Do commitu nepatří data, exporty z portálu, výstupy grafů ani `.env`. Chybí-li pravidlo
  v `.gitignore` a `.gitignore` je ve scope, doplň ho; jinak to napiš do hand-off note.
- Nepushnutá větev se aktualizuje `git rebase`, pushnutá `git merge` (nepřepisuj historii).

## Kdy je WP hotový

- Definition of Done z `MIGRATION_PLAN.md` §1.8: akceptační kritéria, zelené gates ve worktree
  WP, pokrytí změněného kódu ≥ 85 %, nic mimo scope, dokumentace, hand-off note, review.
- Co se nepodařilo ověřit, je v hand-off note. Neověřená změna se nevydává za hotovou.

## Styl kódu (zkráceně, plné znění v plánu §1.2)

- Čitelnost a objektový návrh: doménové pojmy jako třídy, body rozšíření jako ABC s registrem,
  závislosti konstruktorem, neměnné hodnotové objekty, žádný kód při importu.
- Jednotky v názvech (`temp_c`, `rh_pct`, `duration_s`), žádná magická čísla, interně UTC.
- `logging` místo `print`, NumPy docstringy s jednotkami, žádný zakomentovaný kód ani bannery.

## Styl komunikace

- S ownerem česky; kód, komentáře, docstringy, `docs/` a commity anglicky.
- Přímo a stručně, bez marketingu. Neúspěch nebo pochybnost pojmenuj otevřeně.
- Nerefaktoruj mimo zadání. Co by se mělo opravit jinde, patří do *Out of scope*.
- **Každá delší zpráva ownerovi končí sekcí „Co potřebuju od tebe"**: konkrétní akce
  a rozhodnutí, a co se *nemění* (co dělat nemusí). Když nic, napiš to výslovně. Vysvětlení
  patří nad tuto sekci, ne do ní.
