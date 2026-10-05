# MIGRATION_PLAN.md — SIVIN Meteostations

Závazný plán migrace repozitáře ze sady samostatných skriptů na udržovatelný Python balíček
a statický mapový portál na GitHub Pages.

- **Tento soubor říká, *co* se dělá:** cílová architektura, datové kontrakty, workpackages (WP),
  akceptační kritéria, rozhodnutí vlastníka.
- **[CLAUDE.md](CLAUDE.md) říká, *jak* pracuje Claude**, [CONTRIBUTING.md](CONTRIBUTING.md) je
  zkrácený výtah inženýrských standardů z §1.
- Když si soubory odporují, platí tento plán. Rozpor se nevybírá potichu: napíše se jako otázka
  vlastníkovi (§0.6, v hand-off note sekce *Open questions for the owner*) a pracuje se na něčem jiném.

Vlastník projektu: **Richard Redina** (GitHub `RicRedi`).
Verze plánu: 2.1 (2026-10-05, Q8–Q10 zodpovězeny).

---

## 0. Řízení projektu

### 0.1 Role (agentní tým)

| Role | Kdo | Odpovědnost | Nesmí |
|---|---|---|---|
| **Owner** | Richard | Schvaluje plán a jeho změny, rozhoduje otevřené otázky (§0.6), dodává reálná data a přístupy, **jako jediný merguje** větve do `main`, uzavírá WP. | — |
| **Orchestrátor** | Claude (hlavní session) | Rozkládá práci na WP, zakládá větve a worktree, píše zadání workerům, po workerovi znovu spouští gates, spouští reviewera, řídí opravná kola, pushuje větve, reportuje stav vlastníkovi. | Mergovat, pushovat do `main`, měnit zadání WP bez souhlasu ownera. |
| **Worker** | Claude subagent, 1 na WP | Implementuje přesně jeden WP ve svém worktree a ve svém `Files` scope, píše testy, dokumentaci a hand-off note, commituje. | Sahat mimo `Files` scope, pushovat, měnit kontrakty z §2. |
| **Reviewer** | Claude subagent, nezávislý na workerovi | Reviduje hotový WP proti akceptačním kritériím, Definition of Done (§1.8), správnosti, čitelnosti a OOP návrhu (§1.2); u indexů kontroluje vzorce proti citované literatuře. Výsledek zapíše do hand-off note. | Opravovat kód sám (jen nálezy), schvalovat vlastní práci. |

### 0.2 Životní cyklus WP

```
Planned ──► In progress ──► In review ──► Ready for owner ──► Merged (owner)
                ▲               │
                └── Changes ◄───┘   (max. 2 opravná kola, pak eskalace ownerovi)
```

1. **Orchestrátor** založí větev `wp/<id>-<slug>` z báze podle §0.4 a worktree
   `../wt/wp-<id>`.
2. **Worker** dostane zadání = text WP z §4 + odkaz na §1 a §2. Implementuje, spustí gates (§1.8),
   napíše `docs/wp_log/WP-<id>.md` (šablona §0.7) a commituje.
3. **Orchestrátor** gates nezávisle zopakuje. Červené gates = zpět workerovi, reviewer se nespouští.
4. **Reviewer** zapíše do `docs/wp_log/WP-<id>.md` sekci *Review*: verdikt `APPROVE` nebo
   `CHANGES_REQUESTED` a nálezy seřazené podle závažnosti (blocker / major / minor / nit).
5. Při `CHANGES_REQUESTED` jde WP zpět workerovi (blockery a majory musí být opravené, minory
   opravené nebo zdůvodněné). Po 2. kole bez `APPROVE` orchestrátor WP pushne s otevřenými nálezy
   a předá je ownerovi k rozhodnutí.
6. **Orchestrátor** pushne větev a ohlásí ji ownerovi jako *Ready for owner*.
7. **Owner** zreviduje, případně požádá o změny, a merguje. Nikdo jiný.

### 0.3 Pravidla

1. **Merguje jen owner.** Žádný agent nemerguje, nepushuje do `main` a neotevírá PR, pokud o to
   owner výslovně nepožádá.
2. **`Files` scope je závazný.** Worker mění jen soubory ve scope svého WP (plus vlastní testy,
   `__init__.py` re-exporty a `docs/wp_log/WP-<id>.md`). Co je potřeba opravit jinde, zapíše do
   hand-off note do sekce *Out of scope*.
3. **Kontrakty z §2 jsou zmrazené.** Změna schématu dat, registru čidel nebo datového kontraktu
   webu je samostatná změna plánu, kterou schvaluje owner.
4. **Žádná vymyšlená data.** Testovací data jsou syntetická a jako syntetická označená. Žádné číslo
   v dokumentaci nebo testu se nevydává za měření z reálných čidel, pokud z nich nepochází.
5. **Žádné vymyšlené citace.** Literatura se uvádí jen taková, kterou agent zná s jistotou
   (autoři, rok, název, zdroj). DOI se uvádí jen ověřené; neověřené se označí `[DOI neověřeno]`.
   Ze sandboxu agentů není `doi.org` dostupné, ověření DOI je položka pro ownera.
6. **Přihlašovací údaje nikdy v repozitáři.** Lokálně v `.env`, v Actions v GitHub Secrets.
7. **Neověřené = nehotové.** Co nešlo ověřit (chybí reálný export, portál není dostupný), se
   píše do hand-off note, ne do textu jako fakt.
8. **Malé odbočky ano, rozšiřování ne.** Nápad mimo plán jde do *Out of scope* nebo jako návrh
   ownerovi.

### 0.4 Větve a pořadí merge

- Plánovací commit (tento soubor, `CLAUDE.md`, `CONTRIBUTING.md`) je na větvi
  `claude/funny-sagan-jge9is`. **Merguje se do `main` jako první.**
- Každý WP má větev `wp/<id>-<slug>`. Báze:
  - WP-0.1 vychází z plánovací větve,
  - WP vlny 1 (§5) vychází z `wp/0.1-foundation`,
  - výjimka: WP-3.1 (web) nezávisí na Python kódu, vychází přímo z plánovací větve a běží
    souběžně s WP-0.1,
  - pozdější vlny vychází z `main` ve chvíli, kdy jsou jejich závislosti mergnuté;
  - vlna 2 vychází z commitu plánu verze 2 (větev `claude/funny-sagan-jge9is` nad `main`),
    plánovací větev se proto opět merguje jako první.
- Doporučené pořadí merge: plánovací větev → `wp/0.1-foundation` → libovolně WP vlny 1.
  Větve vlny 1 obsahují commity WP-0.1; po jeho merge se v diffu ukáže jen vlastní změna WP.
- Když se `main` posune: nepushnutá větev → `git rebase main`; pushnutá větev →
  `git merge origin/main` (žádný přepis historie).
- Commity: conventional commits v angličtině s ID WP, např.
  `feat(quality): detect office-to-field deployment step [WP-1.5]`.

### 0.5 Rozhodnutí vlastníka

| Datum | Rozhodnutí |
|---|---|
| 2026-10-05 | Cílová podoba: statický mapový portál na GitHub Pages, bez databáze. |
| 2026-10-05 | Data čidel mohou být **veřejná**. |
| 2026-10-05 | Poskytovatel (`lemon.e-service.cz`) **nemá API** → sběr dat zůstává přes automatizovaný prohlížeč. |
| 2026-10-05 | Mapový podklad: **zdarma dostupný** (OSM a odvozené), stačí přibližná vizualizace. |
| 2026-10-05 | Kód: **maximální čitelnost a objektově orientovaný návrh** (§1.2). |
| 2026-10-05 | Povinně: **validace vstupu**, **párování dat z různých čidel**, **detekce náhlých přechodů** (čidlo se zapíná v kanceláři a pak se přenese ven → skok v teplotě). |
| 2026-10-05 | Každý index má v `docs/` matematický popis a zdrojovou literaturu. Složka `docs/` je trvalá součást repozitáře. |
| 2026-10-05 | Mikroklima a prostorové srovnání čidel je cíl projektu; plně se rozvine s růstem počtu čidel. |
| 2026-10-05 | Každý WP má vlastní větev. **Merguje výhradně owner.** |
| 2026-10-05 | Vlna 0 a 1 mergnuté do `main`. |
| 2026-10-05 | Q2: portál exportuje **místní čas** (Europe/Prague). |
| 2026-10-05 | Q3: automatická detekce přechodů se **odkládá stranou**. Výchozí předpoklad: čidla měří ve vinici. Pravdou je **log mimo-vinici** (`sensors/offsite_log.yaml`, §2.8), který vede owner ručně (čidlo + od–do). Detektor běží jen v poradním režimu (varování, žádné příznaky). |
| 2026-10-05 | Huglinův koeficient K podle tabulky šířkových pásem, pro naše čidla **K = 1,06**. |
| 2026-10-05 | QC: **chybí-li v daném čase jedna veličina, je celé měření neplatné** (`MISSING` při chybějící teplotě *nebo* vlhkosti; denní agregace bere jen řádky s oběma veličinami). Ruší per-variable výjimky z WP-0.1/1.2/3.1. |
| 2026-10-05 | Literaturu a parametry indexů **ověřit** (agent s přístupem na web), výsledek v `docs/literature-verification.md`. |
| 2026-10-05 | Web: dvě osy v jednom grafu, nová barevná škála mapy, předvolby oken končí koncem dat, tolerantní čtení volitelných polí kontraktu — **schváleno**. Měsíční soubory `raw/<YYYY-MM>` jsou **měsíce v UTC** (upřesnění §2.6). |
| 2026-10-05 | Sloupec `source` v úložišti: **krátký identifikátor exportu** (časová značka exportu), plný název souboru jen v `RunRecord`. |
| 2026-10-05 | Q5: aktualizace **1× denně v 6:00 místního času**. |
| 2026-10-05 | Q7: owner přidá Secrets `SIVIN_USER`, `SIVIN_PASSWORD`; lokálně `.env` podle `.env.example`. |
| 2026-10-05 | Q8: portál pojmenovává soubory **s mezerami a závorkou** (`MeteoData_8615620 77799986 (VUT)_….csv`); podtržítka vznikla až při nahrání. Podpora podtržítek z WP-0.2 zůstává jako tolerance. |
| 2026-10-05 | Q9: **srážky, kumulativní srážky a napětí baterie se převezmou do dat** (rozšíření §2.5/§2.6, WP-1.9); modely chorob se srážkami ve WP-2.5. Pravidlo platnosti řádku se týká jen teploty a vlhkosti. |
| 2026-10-05 | Q10: čidlo 77799986 bylo v celém exportu (30. 7. 2025 – 1. 3. 2026) mimo vinici → první záznam `service` v logu mimo-vinici (WP-1.8). |
| 2026-10-05 | Vyřazení čidla = `status: retired` v registru; data se nemažou (návrh orchestrátora, owner nerozporoval). |
| 2026-10-05 | Interní poznámky (`notes` čidla, `note` umístění) se **nepublikují** na webu; `sensors.geojson` na webu je veřejná projekce registru. |
| 2026-10-05 | Výběr čidel na webu škálovatelný: rozbalovací seznam s vyhledáváním, **dvě úrovně členění obec → viniční trať** (WP-3.5). Registr dostává pole `municipality` a `track` místo `site`. |

### 0.6 Otevřené otázky na ownera

| # | Otázka | Proč | Blokuje |
|---|---|---|---|
| Q1 | ✅ Dodán reálný CSV export čidla 77799986 (§0.6.1). | — | — |
| Q2 | ✅ Místní čas. | — | — |
| Q3 | ✅ Nahrazeno logem mimo-vinici (§2.8). | — | — |
| Q4 | Odrůda a název vinice pro každé čidlo. | Odrůdové parametry fenologických modelů (WP-2.1), popisky v mapě. | Nic (volitelné pole) |
| Q5 | ✅ 1× denně v 6:00 místního času. | — | — |
| Q6 | Zveřejnit repozitář a zapnout GitHub Pages se zdrojem „GitHub Actions" (owner, před dokončením WP-4.1). | Nasazení webu. | Deploy ve WP-4.1 |
| Q7 | Přidat Secrets `SIVIN_USER`, `SIVIN_PASSWORD` (owner). | Automatické stahování. | První ostrý běh WP-4.1 |
| Q8 | ✅ Portál: mezery a závorka; podtržítka z nahrání. | — | — |
| Q9 | ✅ Převzít (WP-1.9, WP-2.5). | — | — |
| Q10 | ✅ Ano; záznam v logu odvozen z dat. | — | — |
| Q11 | Exporty zbývajících tří čidel (stačí jednou), případně XLSX variantu. | Ověření parserů na všech čidlech. | Nic |

### 0.6.1 Zjištění z reálného exportu (Q1, 2026-10-05)

Soubor `MeteoData_8615620_77799986_VUT_20260301_223842.csv` (čidlo 77799986):
- CSV, UTF-8, CRLF, `;`, desetinná čárka, první řádek `Meteo Data;`, na konci řádek `;`.
- Sloupce: `Datum a čas;Teplota (°C);Vlhkost (%);Srážky (mm);Celkové srážky (mm);Nabití baterie (V)`.
- Řazení **od nejnovějšího**; čas místní ve formátu `YYYY-MM-DD HH:MM:SS`.
- Parser z vlny 1 obsah načetl správně (3520 řádků, otočení pořadí, převod do UTC), **neprošel
  název souboru s podtržítky** (`SensorId`) → oprava ve WP-0.2.
- Medián kroku **1830 s** (legacy uváděl 1825 s); mezera 139 dní (31. 7. – 17. 12. 2025).
- 17. 12. 2025 – 1. 3. 2026 pokojový režim (viz Q10).

### 0.7 Šablona hand-off note (`docs/wp_log/WP-<id>.md`)

```markdown
# WP-<id> — <title>

## Summary
What was done, 3–6 sentences.

## Changed files
## How it was verified
Which gates ran and with what result (command → result), coverage of changed code.

## What did not work / what was not verified
## Out of scope
Findings that belong elsewhere (file, problem, proposal).

## Open questions for the owner

## Review
Verdict: APPROVE | CHANGES_REQUESTED  (round N)
| Severity | File:line | Finding | Status |
```

Hand-off notes jsou v angličtině (jsou součástí `docs/`).

---

## 1. Inženýrské standardy

### 1.1 Prostředí a nástroje

- **Python 3.12** (legacy kód už syntaxi 3.12 používá). Virtuální prostředí `.venv` v kořeni.
- Balíček `sivin` v `src/` layoutu, závislosti **jen v `pyproject.toml`**
  (runtime + extras `ingest`, `viz`, `dev`). `requirements.txt` zaniká (WP-0.1).
- Instalace: `python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev,ingest,viz]"`.
- Gates: `make lint` (ruff check + ruff format --check), `make type` (mypy --strict nad `src/`),
  `make test` (pytest), `make cov` (pokrytí). Web: `npm run lint`, `npm run typecheck`,
  `npm test`, `npm run build` v `web/`.
- CI (GitHub Actions) spouští stejné gates na každý push do `wp/**` a `claude/**`.

### 1.2 Objektový návrh a čitelnost

Cíl: kód, který se čte jako popis domény. Konkrétně:

1. **Doménové pojmy jsou třídy.** `Sensor`, `Placement`, `SensorRegistry`, `MeasurementSeries`,
   `ExportParser`, `QualityCheck`, `DeploymentDetector`, `SensorAligner`, `ClimateIndex`,
   `MeasurementStore`, `PortalClient`, `SiteBuilder`.
2. **Body rozšíření jsou abstraktní třídy (`abc.ABC`) nebo `Protocol`.** Nové chování =
   **nová třída, která se zaregistruje** (registr přes dekorátor), nikdy nová větev v `if/elif`.
   Příklad: nový index = nová podtřída `ClimateIndex` s `@index_registry.register("huglin")`.
3. **Závislosti přichází konstruktorem** (dependency injection); objekty z konfigurace staví
   továrny. Žádné singletony, žádný modulový mutable stav, **žádný kód, který se spustí při
   importu**.
4. **Hodnotové objekty jsou neměnné:** `@dataclass(frozen=True, slots=True)` nebo pydantic model
   s `frozen=True`.
5. **Jedna třída = jedna odpovědnost.** Třída s více než ~200 řádky nebo metoda s více než ~40
   řádky je signál k rozdělení.
6. **Čistá matematika** (vzorec indexu, Magnusova rovnice) smí být v malé čisté funkci nebo
   `@staticmethod`, testované izolovaně. Třída indexu ji orchestruje (výběr období, agregace,
   úplnost dat).
7. **Pojmenování:** `snake_case` funkce a proměnné, `PascalCase` třídy, `UPPER_SNAKE` konstanty,
   `_private` pomocníci. **Jednotky v názvech:** `temp_c`, `rh_pct`, `duration_s`,
   `elevation_m`, `vpd_kpa`.
8. **Žádná magická čísla.** Prahy a parametry jdou z konfigurace nebo z pojmenované konstanty
   s komentářem, odkud hodnota pochází (citace).
9. **Logging:** `logger = logging.getLogger(__name__)` v každém modulu, konfigurace logování jen
   v `cli.py`. V `src/` žádný `print`.
10. **Žádný mrtvý kód:** žádný zakomentovaný kód, žádné ASCII-art hlavičky, žádné autorské bannery
    ve zdrojových souborech (autorství je v gitu a v `pyproject.toml`).
11. **Docstringy v NumPy stylu.** Každá veřejná třída a funkce dokumentuje parametry, návratové
    hodnoty a **jednotky**.

### 1.3 Konfigurace

- Jeden soubor `config/sivin.yaml`, sekce na subsystém. Každá sekce je pydantic v2 model
  s `frozen=True, extra="forbid"`: překlep v klíči selže při startu s cestou ke klíči.
- Cesty v konfiguraci jsou **relativní ke kořeni projektu** a resolvují se přes
  `ProjectPaths`. Absolutní uživatelské cesty se nikdy necommitují; stroj-specifické hodnoty jdou
  přes proměnné prostředí.
- Tajné hodnoty jen z prostředí (`SIVIN_USER`, `SIVIN_PASSWORD`), nikdy z YAML.
- Každé nové pole konfigurace má popis a jednotku (`Field(description=...)`).

### 1.4 Testy

- pytest; unit testy porovnávají s **ručně spočítanými** hodnotami, ne s tím, co kód zrovna vypíše.
- Každý index má test na malém ručně spočitatelném příkladu (např. 3 dny, známé Tmin/Tmax).
- Syntetické fixtures v `tests/fixtures/` (generované deterministicky, se seedem); jsou
  označené jako syntetické.
- Pokrytí kódu, který WP přidá nebo změní: **≥ 85 %**. `cli.py` a vykreslování grafů jsou výjimkou.
- Testy nesmí sahat na síť ani na portál. Portál se testuje přes mock / uložené HTML.

### 1.5 Čas a jednotky

- Interně **vždy UTC** (`datetime64[ns, UTC]`). Převod ze zdrojové zóny při parsování, převod
  do `Europe/Prague` jen pro zobrazení a pro denní agregace (den = místní kalendářní den).
- Teplota °C, relativní vlhkost %, tlak kPa, nadmořská výška m, čas v sekundách.

### 1.6 Web

- `web/`: TypeScript (strict), Vite, Leaflet (mapa), uPlot (časové řady). Bez frameworku nebo
  s jedním lehkým; UI složené z tříd komponent (`MapView`, `SensorPanel`, `TimeWindowControl`,
  `SeriesChart`, `DataClient`).
- Žádné API klíče ve frontendu. Mapové podklady jen bezplatné (OSM, OpenTopoMap) s atribucí.
- Gates: ESLint, `tsc --noEmit`, Vitest, `vite build`.

### 1.7 Dokumentace

- `docs/` je trvalá. Struktura:
  - `docs/architecture.md` — přehled architektury (udržuje se s §2),
  - `docs/indices/<index_id>.md` — jeden soubor na index (šablona níže),
  - `docs/quality-control.md`, `docs/data-format.md`, `docs/sensors.md`, `docs/ingest.md`,
  - `docs/wp_log/WP-<id>.md` — hand-off notes.
- Dokumentace v `docs/` je **anglicky** (kód a vzorce), plán a `CLAUDE.md` česky.
- Matematika v GitHub markdownu (`$...$`, `$$...$$`).

**Šablona `docs/indices/<index_id>.md`:**

```markdown
# <Název indexu> (`<index_id>`)
## Purpose — co index říká o vinné révě / vegetačním cyklu
## Definition — vzorec (LaTeX), význam všech symbolů a jednotky
## Period and aggregation — období, denní agregace, požadovaná úplnost dat
## Parameters — tabulka: název v configu, výchozí hodnota, jednotka, zdroj hodnoty
## Interpretation — třídy / prahy s citací
## Assumptions and limitations — co platí pro naše data (jen T a RH, krok ~30 min)
## Implementation — třída, modul, test
## References — plné citace; DOI jen ověřené
```

### 1.8 Definition of Done (každý WP)

- [ ] Akceptační kritéria WP splněná.
- [ ] `make lint type test` zelené ve worktree WP (u webu `npm run lint typecheck test build`).
- [ ] Pokrytí změněného kódu ≥ 85 % (mimo výjimky z §1.4).
- [ ] Nic mimo `Files` scope (§0.3/2).
- [ ] Nová konfigurační pole mají popis a jednotku.
- [ ] Nový index má `docs/indices/<id>.md` podle šablony.
- [ ] Hand-off note `docs/wp_log/WP-<id>.md` včetně toho, co nefungovalo a co nebylo ověřeno.
- [ ] Review `APPROVE`, nebo otevřené nálezy výslovně předané ownerovi.

---

## 2. Cílová architektura a kontrakty

### 2.1 Přehled

```
                   ┌────────────── GitHub Actions (cron, např. 1× za hodinu) ──────────────┐
lemon.e-service.cz │ PortalClient ─► ExportParser ─► InputValidator ─► MeasurementStore     │
   (Excel export)  │   (Selenium)      (xlsx/csv)      (schéma, čas)    (větev `data`)      │
                   │                                                         │              │
                   │   QualityPipeline (rozsah, spike, step, stuck, nasazení) │              │
                   │   SensorAligner (párování čidel)   ClimateIndex (indexy)  ▼              │
                   │                                       SiteBuilder ─► site/data/*.json   │
                   └──────────────────────────────────────────────┬───────────────────────────┘
                                                                  ▼ deploy
                                          GitHub Pages: web/ (Leaflet + uPlot) čte site/data
```

### 2.2 Struktura repozitáře (cílová)

```
pyproject.toml, Makefile, .pre-commit-config.yaml
config/sivin.yaml                    # jediná konfigurace
sensors/sensors.geojson              # registr čidel (jediný zdroj pravdy)
sensors/sensors.schema.json
src/sivin/
  cli.py                             # vstupní bod `sivin …`
  config.py, paths.py, logging_setup.py
  core/        ids.py (SensorId), schema.py (MeasurementSeries, sloupce), flags.py (QcFlag),
               timeutil.py, daily.py (DailyWeather), season.py
  registry/    model.py (Sensor, Placement), registry.py (SensorRegistry), gpx.py
  ingest/      parsers/ (ExportParser + implementace), validation.py (InputValidator),
               portal/ (PortalClient, PortalSettings)
  storage/     store.py (MeasurementStore)
  quality/     checks/ (QualityCheck + implementace), deployment.py (DeploymentDetector),
               pipeline.py (QualityPipeline)
  alignment/   aligner.py (SensorAligner)
  analytics/   base.py (ClimateIndex, IndexResult, registr), thermal/, ripening/, disease/,
               spatial/
  site/        builder.py (SiteBuilder)  # výstup podle kontraktu §2.6
  viz/         publikační grafy a animace (port legacy skriptů)
web/                                  # frontend
docs/                                 # §1.7
tests/
.github/workflows/  ci.yml, pipeline.yml
legacy/                               # dočasně původní skripty, do WP-5.2
```

### 2.3 Tok dat a aktualizace (odpověď na otázku „spouští se Action při otevření stránky?")

**Ne.** GitHub Pages je čistě statický hosting; otevření stránky nemůže spustit Action (návštěvník
by k tomu potřeboval GitHub token a čekal by minuty). Místo toho:

1. Workflow `pipeline.yml` běží **podle cronu** (návrh: každou hodinu; čidla měří ~každých 30 min)
   a navíc ručně tlačítkem *Run workflow* (`workflow_dispatch`).
2. Běh: přihlášení na portál → stažení exportů všech čidel → parsování a validace → připojení
   nových záznamů do úložiště (duplicity se zahodí) → QC → indexy → vygenerování `site/data` →
   build webu → deploy na Pages. Vše v **jednom** workflow (push tokenem `GITHUB_TOKEN` další
   workflow nespouští).
3. Stránka při načtení jen stáhne poslední vygenerované JSON soubory. Data jsou tedy stará
   nejvýš jeden interval cronu (+ zpoždění cronu na GitHubu, typicky minuty).
4. Úložiště měření je **větev `data`** (oddělená historie, `main` zůstává čistý). Žádná databáze.
5. Pozn.: v neaktivním veřejném repozitáři GitHub plánované workflow po 60 dnech vypíná; commity
   do větve `data` se ověří jako aktivita v WP-4.1.

### 2.4 Identita čidel

- **Kanonické ID = 8místné sériové číslo zařízení**, např. `77678271`.
- `SensorId` (WP-0.1) umí parsovat všechny dnešní varianty:
  portálový název `8615620 77678271`, GPX název `77678271 (VUT)`, název souboru
  `MeteoData_8615620 77678271 (VUT)_20260301_223857.csv`. Legacy 4místný sufix (`8271`) se
  převádí jen přes registr (není jednoznačný).
- **Registr `sensors/sensors.geojson`** (FeatureCollection, schéma v `sensors.schema.json`):

```json
{
  "type": "Feature",
  "geometry": { "type": "Point", "coordinates": [16.673002, 48.880215] },
  "properties": {
    "id": "77678271",
    "portal_name": "8615620 77678271",
    "label": "77678271 (VUT)",
    "municipality": null,
    "track": null,
    "variety": null,
    "status": "active",
    "placements": [
      { "from": "2025-12-01T00:00:00Z", "to": null,
        "lon": 16.673002, "lat": 48.880215, "elevation_m": 183.9,
        "note": "imported from sensor_location.gpx" }
    ],
    "notes": null
  }
}
```

- `geometry` = aktuální umístění (poslední `placement`). `placements` je historie: **`from`
  každého umístění je okamžik nasazení** a slouží jako pravdivá hodnota pro detektor přechodů.
  Přesun čidla = uzavření `to` a nové umístění; data se tak nepřiřadí ke špatnému místu.
- Hodnoty `from` v migraci z GPX jsou zástupné, dokud owner nedodá Q3.

### 2.5 Kanonická data a úložiště

**`MeasurementSeries`** (WP-0.1, `sivin.core.schema`) je obal nad `pandas.DataFrame`, který při
vytvoření validuje:

| Sloupec | Typ | Jednotka | Pozn. |
|---|---|---|---|
| `sensor_id` | `str` | — | kanonické ID |
| `timestamp_utc` | `datetime64[ns, UTC]` | — | vzestupně, bez duplicit |
| `temp_c` | `float64` | °C | `NaN` = chybí |
| `rh_pct` | `float64` | % | `NaN` = chybí |
| `precip_mm` | `float64` | mm | srážky za interval od předchozího vzorku (sloupec `Srážky (mm)`); `NaN` = chybí; od WP-1.9 |
| `precip_total_mm` | `float64` | mm | čítač kumulativních srážek (`Celkové srážky (mm)`); slouží ke kontrole a doplnění mezer; od WP-1.9 |
| `battery_v` | `float64` | V | napětí baterie (`Nabití baterie (V)`); od WP-1.9 |
| `qc` | `int32` (`QcFlag`) | — | 0 = bez nálezu; doplňuje QC |
| `source` | `str` | — | volitelné, název zdrojového souboru |

**Úložiště** (WP-1.4) na větvi `data`:

```
data/raw/<sensor_id>/<YYYY>.csv     # timestamp_utc,temp_c,rh_pct,precip_mm,precip_total_mm,battery_v,source
                                    # (ISO 8601 se Z; starší soubory bez nových sloupců se čtou s NaN)
data/derived/events/<sensor_id>.json
data/runs/<YYYY-MM-DD>.jsonl        # souhrn běhu: stažené soubory, validace, počty nových řádků
```

Zápis je idempotentní: opakovaný import stejného exportu nic nezmění.

**Odhad objemu:** ~17 500 záznamů / čidlo / rok ≈ 0,5 MB CSV. Pro desítky čidel bez problému;
při stovkách čidel je připravená cesta Parquet + DuckDB-WASM (bez serveru).

### 2.6 Datový kontrakt webu (`site/data/`, `schema_version: 1`)

Generuje `SiteBuilder` (WP-3.2), čte `web/` (WP-3.1). Do té doby web pracuje nad fixture se
stejným tvarem. Pole jsou **sloupcová** (rychlé pro uPlot), čas = Unix sekundy UTC, chybějící
hodnota = `null`.

```
site/data/manifest.json
site/data/sensors.geojson                        # kopie registru
site/data/latest.json
site/data/series/<sensor_id>/raw/<YYYY-MM>.json
site/data/series/<sensor_id>/daily.json
site/data/events/<sensor_id>.json
site/data/indices/<season>.json
```

```jsonc
// manifest.json
{ "schema_version": 1, "generated_at": "2026-10-05T10:00:00Z",
  "display_timezone": "Europe/Prague",
  "variables": [
    { "id": "temp_c", "unit": "°C", "label": { "cs": "Teplota", "de": "Temperatur", "en": "Temperature" } },
    { "id": "rh_pct", "unit": "%",  "label": { "cs": "Vlhkost", "de": "Feuchtigkeit", "en": "Humidity" } } ],
  "sensors": { "77678271": { "first_t": 1764547200, "last_t": 1791190800,
                             "raw_months": ["2025-12", "2026-01"] } },
  "seasons": [2026],
  "indices": [ { "id": "huglin", "unit": "°C·d", "doc": "docs/indices/huglin.md",
                 "label": { "cs": "Huglinův index", "de": "Huglin-Index", "en": "Huglin index" } } ] }

// latest.json
{ "generated_at": "…", "sensors": { "77678271": { "t": 1791190800, "temp_c": 12.4, "rh_pct": 81.0,
                                                  "qc": 0, "stale": false } } }

// series/<id>/raw/<YYYY-MM>.json
{ "sensor_id": "77678271", "t": [1767225600, 1767227425], "temp_c": [1.2, 1.1],
  "rh_pct": [92.0, null], "precip_mm": [0.0, 0.2], "battery_v": [3.6, 3.6], "qc": [0, 1] }
// precip_mm a battery_v od WP-1.9 (volitelná pole, web je musí tolerovat chybějící)

// series/<id>/daily.json   (den = místní kalendářní den Europe/Prague)
{ "sensor_id": "77678271", "date": ["2026-01-01"], "temp_min": [-2.1], "temp_mean": [0.4],
  "temp_max": [3.0], "rh_min": [70.0], "rh_mean": [88.1], "rh_max": [99.0], "coverage": [0.98],
  "precip_sum_mm": [0.4], "battery_min_v": [3.5] }
// precip_sum_mm a battery_min_v od WP-1.9 (volitelná pole; počítají se ze všech přítomných
// hodnot mimo období mimo-vinici / ruční vyřazení, nezávisle na platnosti teploty a vlhkosti)

// events/<id>.json
{ "sensor_id": "77678271", "events": [ { "type": "deployment", "t": 1764590400,
  "source": "detected", "confidence": 0.93, "detail": "step −14.2 °C, diurnal amplitude ×4.1" } ] }

// indices/<season>.json
{ "season": 2026, "computed_at": "…", "sensors": { "77678271": {
    "huglin": { "value": 1834.2, "unit": "°C·d", "coverage": 0.97, "complete": true,
                "class": "temperate_warm" } } } }
```

Hodnoty v příkladech jsou ilustrační, ne měření.

### 2.7 Kvalita dat, validace vstupu, párování a přechody

**Validace vstupu (WP-1.2, `InputValidator`)**: každý stažený soubor projde kontrolami
a výsledkem je `ValidationReport` (seznam nálezů se závažností). Soubor s chybou se **nezapíše
do úložiště** a běh pokračuje dalším souborem (karanténa + záznam v `data/runs/`).
Kontroly: soubor není prázdný ani useknutý; očekávané sloupce (s aliasy názvů a jednotek);
čísla s desetinnou čárkou; parsovatelné časové značky; duplicity; monotónní čas; ID čidla
z obsahu/názvu souboru odpovídá registru; fyzikálně možné hodnoty (hrubá mez, jemné meze řeší QC).

**QC příznaky (`QcFlag`, `enum.IntFlag`, WP-0.1):**

| Příznak | Bit | Význam | Vylučuje z indexů |
|---|---|---|---|
| `MISSING` | 1 | chybí teplota **nebo** vlhkost — celé měření je neplatné (rozhodnutí 2026-10-05) | ano |
| `OUT_OF_RANGE` | 2 | mimo fyzikální / klimatologický rozsah | ano |
| `SPIKE` | 4 | izolovaný výkyv (návrat k předchozí úrovni) | ano |
| `STEP` | 8 | náhlý trvalý skok úrovně | ne (informativní) |
| `STUCK` | 16 | zaseknutá hodnota (persistence) | ano |
| `PRE_DEPLOYMENT` | 32 | čidlo neměřilo ve vinici (kancelář, servis, doprava) — podle logu mimo-vinici §2.8 | ano |
| `NEIGHBOR_OUTLIER` | 64 | nesouhlasí se sousedními čidly | ne (informativní) |
| `TIMESTAMP_SUSPECT` | 128 | nejednoznačný čas (přechod letního času), nepravidelný krok | ne |
| `MANUAL_EXCLUDE` | 256 | ručně vyřazeno ownerem | ano |

Maska vyloučení je v konfiguraci. Metodika kontrol rozsahu, kroku a persistence vychází
z Zahumenský (2004), prahy jsou v konfiguraci a ladí se na reálných datech.

**Detekce přechodů (WP-1.5, `DeploymentDetector`)**: čidlo se zapíná v kanceláři (stabilní
~20–25 °C, malý denní chod, nízká vlhkost) a pak se přenese ven (skok teploty a vlhkosti
a výrazně větší denní amplituda). Detektor:
1. hledá body změny v **úrovni i rozptylu** (Gaussovská věrohodnost na kumulativních součtech,
   O(n); binární segmentace pro více přechodů — např. odvoz na servis a zpět),
2. kandidáta potvrzuje změnou režimu: poměr denní amplitudy po/před a vzdálenost od „pokojového"
   pásma,
3. výsledkem jsou `DeploymentEvent` (čas, typ `deployment` / `retrieval` / `step`, jistota, popis),
4. záznamy před nasazením dostanou `PRE_DEPLOYMENT`,
5. když registr obsahuje `placement.from`, je pravdivou hodnotou; rozdíl detekce od registru nad
   práh = varování v souhrnu běhu.
Události se zobrazují v grafu na webu jako značky.

**Od 2026-10-05 (rozhodnutí ownera):** zdrojem pravdy pro `PRE_DEPLOYMENT` je log mimo-vinici
(§2.8). `DeploymentDetector` běží ve výchozím stavu **jen v poradním režimu**: hlásí podezřelé
úseky jako varování („možné nezapsané období mimo vinici") a nic neoznačuje.

**Párování dat z různých čidel (WP-1.6, `SensorAligner`)**: dva významy, oba řešené.
1. *Soubor → čidlo*: přes `SensorId` a registr (WP-0.1, WP-1.1).
2. *Časové zarovnání*: čidla měří s periodou ~1825 s a jejich hodiny nejsou synchronní (časové
   značky driftují). `SensorAligner` zarovná řady na společnou mřížku (konfigurovatelný krok,
   výchozí 30 min) metodou *nearest within tolerance* nebo lineární interpolací s maximální
   délkou mezery; výstupem je široká tabulka `čas × čidlo` pro každou veličinu plus maska
   platnosti. Používá ji QC (`NEIGHBOR_OUTLIER`), prostorová analytika (WP-2.4) a srovnávací
   grafy.

### 2.8 Log mimo-vinici (`sensors/offsite_log.yaml`)

Ručně vedený soubor ownera: kdy čidlo **neměřilo ve vinici** (kancelář, servis, doprava,
zapůjčení). Měření v těchto úsecích dostanou `PRE_DEPLOYMENT`, nepočítají se do indexů a web je
v grafu zobrazí jako šedý pás (data se nekreslí jako venkovní).

```yaml
# Periods when a sensor was NOT measuring in the vineyard.
# Times are local (Europe/Prague) unless an explicit offset or Z is given.
# 'to: open' (or 'to: null') means the sensor is still off site; an empty 'to:' is an error.
entries:
  - sensor: "77799986"          # 8-digit serial (any name variant accepted)
    from: "2025-12-17 12:00"
    to:   "2026-03-15 09:00"
    reason: office              # office | service | transport | storage | other
    note: "winter storage in the office"
```

Validace (`sivin` při každém běhu i v testech): známé čidlo, `from < to`, úseky jednoho čidla se
nepřekrývají, `reason` z výčtu. Chybný log zastaví běh pipeline s jasnou chybou (raději žádná
aktualizace než špatně označená data). Úprava: přímo v GitHubu, později i v režimu správce na webu
(WP-3.3).

Kontrakt webu (§2.6) se rozšiřuje o intervalovou událost v `events/<id>.json`:
`{ "type": "off_site", "t": <start>, "t_end": <end | null>, "source": "log", "detail": "<reason: note>" }`.

---

## 3. Katalog analytických ukazatelů

Jen z teploty (T) a relativní vlhkosti (RH). Každý ukazatel = třída `ClimateIndex` + soubor
`docs/indices/<id>.md`. Denní agregace z `DailyWeather` (WP-0.1); den se započítá jen při
úplnosti ≥ `analytics.min_daily_coverage` (konfigurace). Výsledek nese `coverage` a `complete`.

### 3.1 Akumulace tepla a fenologie (WP-2.1)

| ID | Ukazatel | Podstata | Literatura |
|---|---|---|---|
| `gdd_winkler` | GDD / Winklerův index | $\sum \max(0, T_{mean}-10)$, 1. 4.–31. 10., kumulativní křivka, Winklerovy regiony | Amerine & Winkler (1944); Winkler et al. (1974) |
| `huglin` | Huglinův heliotermický index | $\sum \max\left(0, \frac{(T_{mean}-10)+(T_{max}-10)}{2}\right)\cdot K$, 1. 4.–30. 9., K podle zeměpisné šířky | Huglin (1978); Tonietto & Carbonneau (2004) |
| `gst` | Průměrná teplota vegetačního období | průměr $T_{mean}$ 1. 4.–31. 10., třídy cool / intermediate / warm / hot | Jones (2006); Jones et al. (2010) |
| `bedd` | Biologicky efektivní stupeňodny | GDD s horní mezí 19 °C a korekcí na denní teplotní rozsah | Gladstones (1992) |
| `budburst` | Odhad rašení | tepelný součet nad bází od zvoleného data; parametry konfigurovatelné, **orientační** dokud není kalibrace | García de Cortázar-Atauri et al. (2009) |
| `gfv` | Model GFV (kvetení, zaměkání) | $\sum (T_{mean}-0)$ od 1. 3. do kritického součtu $F^*$; odrůdové $F^*$ | Parker et al. (2011, 2013) |
| `gsr` | Model GSR (cukernatost) | $\sum (T_{mean}-0)$ od 1. 4. do $F^*$ pro 170–220 g/l | Parker et al. (2020) |

Fenologické modely potřebují kalibraci na místních pozorováních → v pozdější fázi fenologický
deník (BBCH) jako soubor v repozitáři (návrh, mimo tento plán).

### 3.2 Kvalita zrání a rizika (WP-2.2)

| ID | Ukazatel | Podstata | Literatura |
|---|---|---|---|
| `cool_night` | Cool Night Index | průměr denních minim v září (s. polokoule) | Tonietto & Carbonneau (2004) |
| `dtr_ripening` | Denní teplotní rozsah ve zrání | průměr $T_{max}-T_{min}$ v konfigurovatelném okně (výchozí od modelovaného zaměkání) | Tonietto & Carbonneau (2004) |
| `heat_hours` | Hodiny v teplotních pásmech | hodiny 20–30 °C (optimum), > 30 °C, > 35 °C (tepelný stres) | Mori et al. (2007); Greer & Weedon (2012) |
| `tropical_days_nights` | Tropické dny / noci | $T_{max} \ge 30$ °C / $T_{min} \ge 20$ °C (přenos z legacy) | konvence ČHMÚ / WMO |
| `frost` | Mrazové hodiny a dny | hodiny ≤ 0 °C a ≤ −2 °C, $T_{min}$; mráz **po** modelovaném rašení = kritický | Poling (2008) |
| `winter_freeze` | Zimní mráz | dny s $T_{min}$ pod konfigurovatelnými prahy (výchozí −15 a −20 °C) | Zabadal et al. (2007) |
| `dew_point` | Rosný bod | Magnusova rovnice; dokumentovat použité koeficienty | Alduchov & Eskridge (1996) |
| `vpd` | Deficit tlaku vodní páry | $e_s(T)(1-RH/100)$, denní maximum a hodiny nad prahem | Allen et al. (1998) |

### 3.3 Choroby (WP-2.3)

| ID | Ukazatel | Podstata | Spolehlivost | Literatura |
|---|---|---|---|---|
| `powdery_mildew_gt` | Padlí — Gubler-Thomasův index | jen teplota (souvislé hodiny 21–30 °C, přerušení ≥ 35 °C), index 0–100 | **plná** | Gubler et al. (1999) |
| `botrytis_broome` | Šedá hniloba — Broomeův model | délka ovlhčení a teplota během ní; ovlhčení **odhadnuté** jako RH ≥ práh | **orientační** | Broome et al. (1995) |
| `downy_mildew_310` | Plíseň révová — pravidlo 3-10 (primární infekce) | ≥ 10 °C, ≥ 10 mm srážek za 24–48 h, letorosty ≥ 10 cm; od Q9 jsou srážky k dispozici (WP-2.5) | **orientační** (bez délky letorostů a ovlhčení listu) | Baldacci (1947); Rossi et al. (2008) |

### 3.4 Mikroklima a prostorové srovnání (WP-2.4, pozdější vlna)

- Rozdíly nočních minim vs. nadmořská výška (gradient, inverze, studená jezera) — profil 184–222 m.
- Rozdíl akumulace tepla mezi čidly přepočtený na rozdíl ve dnech do fenofáze.
- Detekce mrazových kapes (systematicky nejnižší minima za radiačních nocí).
- Srovnání s referenční stanicí ČHMÚ (otevřená data) — doplnění mezer, kontrola kalibrace.
Smysl roste s počtem čidel; návrh tříd musí počítat s N čidly, ne se 4.

---

## 4. Workpackages

Formát: **Cíl · Závisí na · Files scope · Úkoly · Akceptační kritéria**.
Pokud není řečeno jinak, WP **nemění** `pyproject.toml`, `cli.py` ani `config/sivin.yaml`
(sdílené soubory). Potřebuje-li novou závislost nebo CLI příkaz, napíše to do hand-off note;
zapojení do CLI a konfigurace dělá integrační WP-1.7 (vlna 2).

### Vlna 0

#### WP-0.1 — Foundation (`wp/0.1-foundation`)
- **Cíl:** kostra balíčku, nástroje a **sdílené kontrakty**, na kterých stojí všechny další WP.
- **Závisí na:** —
- **Files:** `pyproject.toml`, `Makefile`, `.pre-commit-config.yaml`, `.gitignore`,
  `requirements.txt` (smazat), `.github/workflows/ci.yml`, `config/sivin.yaml`,
  `src/sivin/{__init__,cli,config,paths,logging_setup}.py`, `src/sivin/core/**`,
  `src/sivin/analytics/{__init__,base}.py`, prázdné balíčky vlny 1
  (`src/sivin/{registry,ingest,storage,quality,alignment}/__init__.py`), `tests/conftest.py`,
  `tests/core/**`, `docs/architecture.md`,
  `docs/wp_log/WP-0.1.md`.
- **Úkoly:**
  1. `pyproject.toml` (Python ≥ 3.12, extras `ingest`, `viz`, `dev`), ruff (line 100, sady
     `E,F,W,I,N,UP,B,SIM,RUF,NPY,PT,PD`), mypy strict, pytest + coverage. Předem deklarovat
     závislosti potřebné ve vlně 1 (pandas, numpy, pydantic, pyyaml, openpyxl, typer; extra
     `ingest`: selenium; `viz`: matplotlib, seaborn).
  2. `Makefile`: `install lint format type test cov`.
  3. CI workflow: lint, type, test na push do `wp/**`, `claude/**` a na PR.
  4. `.gitignore`: data ignorovat cíleně (`/data/`, `/vystupy/`, `/site/`), ne globálním `*.csv` /
     `*.png`; povolit `tests/fixtures/**`.
  5. `ProjectPaths` (kořen projektu, resolve relativních cest), `SivinConfig` (pydantic, kostra
     sekcí `paths`, `time`, `analytics`), `logging_setup`, CLI kostra (`sivin --version`,
     `sivin config show`).
  6. Kontrakty: `SensorId` (parsování všech variant z §2.4), `MeasurementSeries` (§2.5),
     `QcFlag` (§2.7), `timeutil` (převod zdrojové zóny → UTC, místní den), `DailyWeather`
     (denní Tmin/Tmean/Tmax/RH + `coverage` z očekávaného počtu vzorků), `Season` (období
     zadané měsícem-dnem pro rok), `ClimateIndex` ABC + `IndexResult` + registr indexů.
  7. `docs/architecture.md` (zkrácená §2).
- **Akceptace:** `pip install -e ".[dev]"` na čistém Pythonu 3.12; `make lint type test` zelené;
  `sivin --version` funguje; `SensorId` testované na všech třech reálných variantách názvů;
  `DailyWeather.coverage` testované na ručním příkladu s mezerou; legacy skripty se nemění.

### Vlna 1 (paralelně, všechny závisí jen na WP-0.1)

#### WP-1.1 — Registr čidel (`wp/1.1-sensor-registry`)
- **Files:** `sensors/**`, `src/sivin/registry/**`, `tests/registry/**`, `docs/sensors.md`.
- **Úkoly:** modely `Sensor`, `Placement` (pydantic, frozen); `SensorRegistry` (načtení
  a uložení GeoJSON, vyhledání podle libovolné varianty ID, `placement_at(t)`, aktivní čidla,
  validace: unikátní ID, souřadnice v rozsahu ČR, nepřekrývající se umístění); `GpxImporter`
  (stdlib XML, bez geopandas); JSON Schema `sensors.schema.json` generované z modelu; vytvořit
  `sensors/sensors.geojson` ze `sensor_location.gpx`.
- **Akceptace:** registr obsahuje 4 čidla s polohou a výškou z GPX; round-trip načtení/uložení
  beze změny; validace odmítne duplicitní ID a překrývající se umístění (testy);
  `docs/sensors.md` popisuje, jak přidat, přesunout a vyřadit čidlo.

#### WP-1.2 — Parsování exportů a validace vstupu (`wp/1.2-parsers-validation`)
- **Files:** `src/sivin/ingest/validation.py`, `src/sivin/ingest/parsers/**`,
  `tests/ingest/**` (mimo `tests/ingest/portal/`), `tests/fixtures/exports/**`,
  `docs/data-format.md`.
- **Úkoly:** `ExportParser` ABC + registr; `PortalXlsxParser`, `PortalCsvParser` (formát z legacy:
  `;`, první řádek `Meteo Data;`, desetinná čárka, sloupce `Datum a čas`, `Teplota (°C)`,
  `Vlhkost (%)`; aliasy názvů sloupců v konfiguraci parseru); `LegacyWorkbookParser` (jeden
  `data.xlsx` s listy podle čidel); `InputValidator` + `ValidationReport` (§2.7); převod času do
  UTC s ošetřením letního času (nejednoznačné → `TIMESTAMP_SUSPECT`); syntetické fixtures všech
  formátů včetně vadných souborů.
- **Akceptace:** každý parser vrací validní `MeasurementSeries`; každá kontrola validátoru má
  test s vadným souborem; přechod na zimní čas je otestovaný; `docs/data-format.md` výslovně
  uvádí, že formát **není ověřen na reálném exportu** (do Q1/Q2).

#### WP-1.3 — Klient portálu (`wp/1.3-portal-client`)
- **Files:** `src/sivin/ingest/portal/**`, `tests/ingest/portal/**`, `docs/ingest.md`.
- **Úkoly:** přepsat `chrome_driver.py` objektově: `PortalSettings` (URL, názvy složky a záložky,
  timeouty; z konfigurace, tajné údaje jen z prostředí), `PortalClient` (context manager:
  `login()`, `list_devices()` z DotVVM viewmodelu, `download_export(device)`), `DownloadWatcher`
  (nový soubor = rozdíl množin souborů před a po, ignoruje `.crdownload`, timeout),
  `PortalSession` výsledek (stažené / selhané čidlo + důvod); headless režim; chyba jednoho čidla
  neukončí běh; žádné `time.sleep` tam, kde jde explicitně čekat; Chromium z prostředí
  (`CHROME_BINARY`) i `webdriver-manager`.
- **Akceptace:** unit testy s mockovaným WebDriverem (seznam čidel z uloženého viewmodel JSON,
  timeout jednoho čidla, nový vs. starý soubor); `docs/ingest.md` popisuje lokální spuštění
  a proměnné prostředí; v hand-off note výslovně: **proti reálnému portálu neověřeno**.

#### WP-1.4 — Úložiště měření (`wp/1.4-measurement-store`)
- **Files:** `src/sivin/storage/**`, `tests/storage/**`, `docs/storage.md`.
- **Úkoly:** `MeasurementStore` nad adresářem (`data/raw/<id>/<YYYY>.csv`, §2.5): `append(series)`
  idempotentně (sloučení, deduplikace podle `sensor_id + timestamp_utc`, při konfliktu hodnot
  vyhrává novější zdroj a zaloguje se), `read(sensor_id, start, end)`, `sensors()`, `coverage()`;
  atomický zápis (dočasný soubor + rename); `RunLog` (`data/runs/*.jsonl`).
- **Akceptace:** dvojí import stejných dat = beze změny souborů (test na hash); překryv dvou
  exportů se sloučí správně; čtení přes hranici roku; zápis přežije přerušení (test).

#### WP-1.5 — Kontrola kvality a detekce přechodů (`wp/1.5-quality-control`)
- **Files:** `src/sivin/quality/**`, `tests/quality/**`, `docs/quality-control.md`.
- **Úkoly:** `QualityCheck` ABC + registr; `RangeCheck`, `SpikeCheck`, `StepCheck`,
  `PersistenceCheck`, `GapCheck`/`SamplingCheck`; `DeploymentDetector` (§2.7, bez nových
  závislostí — vlastní implementace změny úrovně a rozptylu přes kumulativní součty);
  `QualityPipeline` (sestaví kontroly z konfigurace, vrátí řadu s `qc` a seznam událostí);
  prahy v pydantic modelu s popisem a citací.
- **Akceptace:** syntetická řada „kancelář 3 dny → venku 10 dní" → detekované nasazení ±1 vzorek
  a `PRE_DEPLOYMENT` na všech záznamech před ním; řada bez přechodu → žádná událost (test na
  falešné poplachy na 60 dnech syntetického venkovního signálu); řada s odvozem na servis →
  `retrieval` + `deployment`; každá kontrola má test; `docs/quality-control.md` s metodikou
  a literaturou.

#### WP-1.6 — Párování čidel v čase (`wp/1.6-sensor-alignment`)
- **Files:** `src/sivin/alignment/**`, `tests/alignment/**`, `docs/alignment.md`.
- **Úkoly:** `SensorAligner` (§2.7): strategie `NearestWithinTolerance` a `LinearInterpolation`
  (max. délka mezery) jako třídy se společným rozhraním; výstup `AlignedPanel` (veličina →
  tabulka čas × čidlo + maska platnosti); respektuje `QcFlag` (vyloučené hodnoty se nepárují).
- **Akceptace:** 3 syntetická čidla s různým driftem hodin → správné zarovnání (ručně spočítaný
  příklad); mezera delší než limit zůstane prázdná; N čidel bez změny kódu.

#### WP-2.1 — Teplotní a fenologické indexy (`wp/2.1-thermal-phenology-indices`)
- **Files:** `src/sivin/analytics/thermal/**`, `tests/analytics/thermal/**`,
  `docs/indices/{gdd_winkler,huglin,gst,bedd,budburst,gfv,gsr}.md`.
- **Úkoly:** indexy z §3.1 jako podtřídy `ClimateIndex`; klasifikace (Winkler, Huglin, GST)
  podle citované literatury; parametry v pydantic modelech; dokumentace podle šablony §1.7.
- **Akceptace:** každý index má ruční testovací příklad; `huglin` a `gdd_winkler` dávají na
  stejných datech stejný výsledek jako legacy `vineyard_analyst.py` (test parity na syntetických
  datech); odrůdové parametry GFV/GSR jen ty, které jsou v citovaných pracích — ostatní
  `[ověřit]`.

#### WP-2.2 — Zrání a rizika (`wp/2.2-ripening-risk-indices`)
- **Files:** `src/sivin/analytics/ripening/**`, `tests/analytics/ripening/**`,
  `docs/indices/{cool_night,dtr_ripening,heat_hours,tropical_days_nights,frost,winter_freeze,dew_point,vpd}.md`.
- **Úkoly:** indexy z §3.2; hodinové ukazatele počítat z délky trvání vzorků (ne počtem
  záznamů — chyba legacy `frost_events_count`); rosný bod a VPD jako čisté funkce + index.
- **Akceptace:** ruční testy; `frost` vrací hodiny, ne počet záznamů; test, že nepravidelný krok
  vzorkování nemění výsledek hodinových ukazatelů.

#### WP-2.3 — Modely chorob (`wp/2.3-disease-models`)
- **Files:** `src/sivin/analytics/disease/**`, `tests/analytics/disease/**`,
  `docs/indices/{powdery_mildew_gt,botrytis_broome,downy_mildew}.md`.
- **Úkoly:** §3.3; Gubler-Thomas jako stavový automat přes dny (třída `GublerThomasModel`);
  Broome s náhradou ovlhčení `RH ≥ práh` jasně označenou jako odhad; `downy_mildew.md`
  zdůvodní, proč se neimplementuje, a co by bylo potřeba (srážkoměr, čidlo ovlhčení listu).
- **Akceptace:** Gubler-Thomas otestovaný na ručně sestavené sekvenci dnů (zahájení, růst,
  pokles, přerušení vedrem, meze 0–100); výstupy Broome nesou příznak `estimated`.

#### WP-3.1 — Webový portál MVP (`wp/3.1-web-mvp`)
- **Závisí na:** jen na kontraktu §2.6 (ne na WP-0.1).
- **Files:** `web/**`, `.github/workflows/web.yml`, `docs/web.md`.
- **Úkoly:** Vite + TypeScript strict; třídy `DataClient` (čte kontrakt §2.6, cache),
  `MapView` (Leaflet, OSM, markery obarvené podle poslední teploty, popisek, stav `stale`),
  `SensorPanel` (detail čidla), `TimeWindowControl` (24 h / 7 d / 30 d / sezóna / vlastní
  rozsah; krok surová / hodinová / denní data), `SeriesChart` (uPlot, teplota a vlhkost,
  značky událostí z `events`), srovnání více čidel v jednom grafu; i18n cs/de/en; fixture
  `web/public/data/` přesně podle §2.6 (syntetická data, označená); responzivní layout.
- **Akceptace:** `npm run lint typecheck test build` zelené; unit testy `DataClient`
  (výběr měsíčních souborů pro okno, sloučení řad) a `TimeWindowControl`; build funguje
  s base path GitHub Pages (`/SIVIN_Mateostations/`); screenshot v hand-off note.

### Vlna 2 (po merge vlny 1; upraveno podle rozhodnutí 2026-10-05)

**Vlna 2a (paralelně, z `main` + plán v2):**

#### WP-0.2 — Rozhodnutí ownera v jádru a reálný export (`wp/0.2-owner-decisions`)
- **Files:** `src/sivin/core/**`, `src/sivin/config.py` (jen výchozí `expected_interval_s`),
  `config/sivin.yaml`, `src/sivin/ingest/**` (mimo `portal/`), `src/sivin/quality/checks/missing.py`,
  `web/src/domain/**` (maska), odpovídající testy, `tests/fixtures/exports/real/**`,
  `docs/architecture.md`, `docs/data-format.md`, `docs/web.md`, `docs/wp_log/WP-0.2.md`.
- **Úkoly:** (1) řádek je platný jen s oběma veličinami: `DailyWeather` a sdílené pomocníky,
  parsery nastaví `MISSING` při chybějící kterékoli veličině, `MissingCheck` výchozí pravidlo
  `any`, web zobrazovací maska = plná `DEFAULT_EXCLUDE` (311); (2) `SensorId` přijme název
  s podtržítky (`MeteoData_8615620_77799986_VUT_20260301_223842.csv`); (3) výchozí
  `expected_interval_s` = 1830 s podle reálných dat; (4) zkrácený reálný export jako fixture
  (s označením „real data, public by owner decision") + regresní test parseru (počet řádků,
  rozsah, otočení pořadí, převod času, extra sloupce ignorovány); (5) dokumentace.
- **Akceptace:** reálný export projde parserem beze změny názvu; testy pro platnost řádku ve
  všech dotčených vrstvách; web gates zelené.

#### WP-1.8 — Log mimo-vinici (`wp/1.8-offsite-log`)
- **Files:** `sensors/offsite_log.yaml`, `sensors/offsite_log.schema.json`,
  `src/sivin/registry/offsite.py` (+ testy), `src/sivin/quality/checks/offsite.py`,
  `src/sivin/quality/pipeline.py`, `src/sivin/quality/deployment.py` (poradní režim),
  `web/src/contract/**`, `web/src/ui/EventMarkers.ts`, `web/src/ui/SeriesChart.ts`,
  `web/scripts/generate-fixture.mjs` + regenerovaná fixture, `docs/sensors.md`,
  `docs/quality-control.md`, `docs/web.md`, `docs/wp_log/WP-1.8.md`.
- **Úkoly:** formát a validace podle §2.8 (`OffSiteLog`, `OffSitePeriod`, loader s místním
  časem); `OffSiteCheck` nastaví `PRE_DEPLOYMENT`; `QualityPipeline` přijme log; detektor
  ve výchozím poradním režimu (jen varování); web vykreslí `off_site` jako šedý pás a v tom úseku
  nekreslí čáru; prázdný log v repozitáři s komentářem a příkladem.
- **Akceptace:** testy validace (překryv, neznámé čidlo, from ≥ to, otevřený konec), místní čas
  přes DST, flagování přesně v intervalu, web test kontraktu a vykreslení pásu.

#### WP-L.1 — Ověření literatury a parametrů (`wp/L.1-literature-verification`)
- **Files:** `docs/literature-verification.md`, `docs/indices/**`, `docs/quality-control.md`
  (reference), parametrické konstanty a docstringy v `src/sivin/analytics/**`, odpovídající testy,
  `docs/wp_log/WP-L.1.md`.
- **Úkoly:** každou citaci a každou hodnotu označenou `[to be verified]` ověřit z dohledatelného
  zdroje (DOI, stránka vydavatele, plný text); tabulka *tvrzení → zdroj → ověřená hodnota → stav*;
  ověřené hodnoty odznačit, chybné opravit (změna výsledků = test + poznámka), neověřitelné
  ponechat označené s vysvětlením. GFV $F^*$ jen z ověřeného zdroje.
- **Akceptace:** žádná hodnota prezentovaná jako literární bez dohledaného zdroje; DOI ověřené.

**Vlna 2b (po merge 2a):**
- **WP-1.7 — Integrace:** CLI `sivin fetch | ingest | qc | indices | sensors check`, jedna
  konfigurace (všechny sekce), `python-dotenv` + `.env.example`, krátký `source` v úložišti,
  log mimo-vinici v běhu QC, `time.expected_interval_s` předávané všem subsystémům,
  end-to-end test nad fixtures včetně reálného exportu.
- **WP-3.2 — SiteBuilder:** `sivin build-site` generuje `site/data` podle §2.6 (včetně
  `off_site`), test kontraktu proti validátorům webu.

**Vlna 2c (po merge 2b):**
- **WP-4.1 — Automatizace:** `pipeline.yml`: cron **6:00 Europe/Prague** (GitHub cron je v UTC →
  dva záznamy 4:00 a 5:00 UTC a krok, který pokračuje jen při místní hodině 6) +
  `workflow_dispatch`; fetch → ingest → QC → indexy → build-site → build webu → deploy Pages;
  data ve větvi `data`; job summary; selhání portálu nesmaže existující data.
- **WP-3.3 — Režim správce na webu:** úpravy `sensors/sensors.geojson` **a**
  `sensors/offsite_log.yaml` přes GitHub API (fine-grained token ownera jen v prohlížeči),
  validace proti schématům před odesláním.

**Vlna 2a-bis (rozhodnutí Q9, paralelně s dokončením 2a, před WP-1.7):**

#### WP-1.9 — Srážky a baterie v datech (`wp/1.9-precip-battery`)
- **Files:** `src/sivin/core/schema.py` (+ `daily.py` pro denní součet srážek a min. napětí),
  `src/sivin/ingest/parsers/**`, `src/sivin/ingest/validation.py`, `src/sivin/storage/**`,
  `src/sivin/quality/checks/{range_check,battery,precip}.py` (+ registrace), `web/src/contract/**`,
  `web/src/domain/**` (jen tolerance nových polí), odpovídající testy a fixtures,
  `docs/data-format.md`, `docs/storage.md`, `docs/quality-control.md`, `docs/architecture.md`,
  `docs/wp_log/WP-1.9.md`.
- **Úkoly:** nové sloupce v `MeasurementSeries` (volitelné, `NaN` = chybí; netýká se jich pravidlo
  platnosti řádku); hodnoty mimo hrubé meze se čtou jako chybějící; aliasy sloupců v parserech (reálný export); úložiště zapisuje a čte nové sloupce
  zpětně kompatibilně (starší CSV bez nich); `DailyWeather` přidá `precip_sum_mm`
  a `battery_min_v`; QC: rozsah srážek (≥ 0, horní mez za interval), konzistence intervalových
  srážek s čítačem (reset čítače = událost, ne chyba), `BatteryCheck` (pod prahem → varovná
  událost „slabá baterie", bez vyřazení dat); web kontrakt toleruje nová pole (zobrazení až WP-3.4).
- **Akceptace:** reálný export načte všech 6 sloupců; staré soubory úložiště se čtou beze změny;
  test resetu čítače; web gates zelené.

**WP-3.5 — Výběr čidel pro větší sítě (`wp/3.5-sensor-picker`, paralelně s WP-4.1):**
registr: pole `municipality` (obec) a `track` (viniční trať) místo `site` (model, schéma,
GeoJSON, migrace souboru, dokumentace); SiteBuilder publikuje veřejnou projekci registru bez
interních poznámek; web: rozbalovací vícenásobný výběr s vyhledáváním, skupinami obec → trať
(vybrat vše ve skupině), štítky vybraných čidel v barvě čáry, limit 8 srovnávaných, vyřazená čidla
na konci a šedě, shlukování markerů v mapě při oddálení, ovládání klávesnicí a mobil.

**Vlna 3 doplněna o:**
- **WP-2.5 — Modely chorob se srážkami:** pravidlo 3-10 pro plíseň révovou (orientační),
  zpřesnění Broomeova modelu (déšť jako začátek ovlhčení), dokumentace v `docs/indices/`.

### Vlna 3

- **WP-2.4 — Mikroklima a prostorové srovnání** (§3.4).
- **WP-3.4 — Analytika na webu:** karty indexů, kumulativní křivky sezóny vs. předchozí roky,
  kalendář rizik, odkazy na `docs/indices`.
- **WP-5.1 — Publikační grafy a animace:** `sivin plot` (jedna / dvě osy, cs/de, PNG/PDF/EPS)
  a `sivin animate` nahrazují `one_variable_plot.py`, `two_variable_plot.py`, `rolling_stats.py`,
  `generate_animation.py`.
- **WP-5.2 — Odstranění legacy a nové README:** smazat legacy skripty a YAML, přepsat README
  (instalace, provoz, odkazy do `docs/`).

---

## 5. Vlny a závislosti

```
WP-0.1 ─┬─ WP-1.1 ─┐
        ├─ WP-1.2 ─┤
        ├─ WP-1.3 ─┼─ WP-1.7 ─┐
        ├─ WP-1.4 ─┤          ├─ WP-3.2 ─┬─ WP-4.1
        ├─ WP-1.5 ─┤          │          └─ WP-3.4
        ├─ WP-1.6 ─┼──────────┼─ WP-2.4
        ├─ WP-2.1 ─┤          │
        ├─ WP-2.2 ─┤          │
        ├─ WP-2.3 ─┘          │
        └─ WP-3.1 ────────────┴─ WP-3.3
                       WP-1.4 ── WP-5.1 ── WP-5.2 (poslední)
```

Vlna 0 a 1 jsou mergnuté. Vlna 2 je rozdělená na 2a (WP-0.2, WP-1.8, WP-L.1 paralelně),
2a-bis (WP-1.9), 2b (WP-1.7, WP-3.2) a 2c (WP-4.1, WP-3.3); každá podvlna začíná po merge
předchozí. WP-2.5 (choroby se srážkami) patří do vlny 3.

---

## 6. Rizika

| Riziko | Dopad | Opatření |
|---|---|---|
| Změna HTML portálu rozbije stahování | výpadek dat | `PortalClient` izolovaný, selektory v konfiguraci, běh selže hlasitě s job summary, existující data zůstanou |
| Formát exportu jiný, než popisuje legacy kód | chybné parsování | Q1; `InputValidator` odmítne soubor místo tichého chybného importu |
| Časová zóna a letní čas | posun dat o hodinu, dvojité záznamy | Q2; `TIMESTAMP_SUSPECT`; testy přechodu |
| Falešné detekce přechodů | vyřazení platných dat | konzervativní prahy, registr jako pravdivá hodnota, události viditelné na webu |
| Fenologické modely bez kalibrace | zavádějící odhady | označení „orientační", parametry v konfiguraci, plán BBCH deníku |
| Neověřené citace / DOI | věrohodnost dokumentace | pravidlo §0.3/5, kontrola reviewerem, ověření DOI ownerem |
| Plánované workflow vypnuté po 60 dnech | data přestanou přibývat | ověřit v WP-4.1, případně keepalive |

---

## 7. Výchozí bibliografie

Úplné citace patří do `docs/indices/*.md`. DOI zde záměrně neuvádím; doplní se po ověření.

- Alduchov, O. A., Eskridge, R. E. (1996). Improved Magnus form approximation of saturation vapor
  pressure. *Journal of Applied Meteorology*, 35, 601–609.
- Allen, R. G., Pereira, L. S., Raes, D., Smith, M. (1998). *Crop evapotranspiration — Guidelines
  for computing crop water requirements.* FAO Irrigation and Drainage Paper 56. FAO, Rome.
- Amerine, M. A., Winkler, A. J. (1944). Composition and quality of musts and wines of California
  grapes. *Hilgardia*, 15(6), 493–675.
- Broome, J. C., English, J. T., Marois, J. J., Latorre, B. A., Aviles, J. C. (1995). Development
  of an infection model for Botrytis bunch rot of grapes based on wetness duration and
  temperature. *Phytopathology*, 85, 97–102.
- García de Cortázar-Atauri, I., Brisson, N., Gaudillère, J. P. (2009). Performance of several
  models for predicting budburst date of grapevine (*Vitis vinifera* L.). *International Journal
  of Biometeorology*, 53, 317–326.
- Gladstones, J. (1992). *Viticulture and Environment.* Winetitles, Adelaide.
- Greer, D. H., Weedon, M. M. (2012). Modelling photosynthetic responses to temperature of
  grapevine (*Vitis vinifera* cv. Semillon) leaves on vines grown in a hot climate. *Plant, Cell
  & Environment*, 35, 1050–1064. `[ověřit]`
- Gubler, W. D., Rademacher, M. R., Vasquez, S. J., Thomas, C. S. (1999). Control of powdery
  mildew using the UC Davis powdery mildew risk index. *APSnet Features*. `[ověřit autory]`
- Huglin, P. (1978). Nouveau mode d'évaluation des possibilités héliothermiques d'un milieu
  viticole. *Comptes Rendus de l'Académie d'Agriculture de France*, 64, 1117–1126.
- Jones, G. V. (2006). Climate and terroir: impacts of climate variability and change on wine.
  In: Macqueen, R. W., Meinert, L. D. (eds.), *Fine Wine and Terroir — The Geoscience
  Perspective*, Geoscience Canada Reprint Series 9, 203–216. `[ověřit strany]`
- Jones, G. V., Duff, A. A., Hall, A., Myers, J. W. (2010). Spatial analysis of climate in winegrape
  growing regions in the western United States. *American Journal of Enology and Viticulture*,
  61(3), 313–326.
- Killick, R., Fearnhead, P., Eckley, I. A. (2012). Optimal detection of changepoints with a
  linear computational cost. *Journal of the American Statistical Association*, 107, 1590–1598.
- Mori, K., Goto-Yamamoto, N., Kitayama, M., Hashizume, K. (2007). Loss of anthocyanins in
  red-wine grape under high temperature. *Journal of Experimental Botany*, 58, 1935–1945.
- Page, E. S. (1954). Continuous inspection schemes. *Biometrika*, 41, 100–115.
- Parker, A. K., García de Cortázar-Atauri, I., van Leeuwen, C., Chuine, I. (2011). General
  phenological model to characterise the timing of flowering and veraison of *Vitis vinifera* L.
  *Australian Journal of Grape and Wine Research*, 17, 206–216.
- Parker, A. K. et al. (2013). Classification of varieties for their timing of flowering and
  veraison using a modelling approach: a case study for the grapevine species *Vitis vinifera* L.
  *Agricultural and Forest Meteorology*, 180, 249–264.
- Parker, A. K. et al. (2020). Temperature-based grapevine sugar ripeness modelling for a wide
  range of *Vitis vinifera* L. cultivars. *Agricultural and Forest Meteorology*, 285–286, 107902.
- Poling, E. B. (2008). Spring cold injury to winegrapes and protection strategies and methods.
  *HortScience*, 43(6), 1652–1662.
- Rossi, V., Caffi, T., Giosuè, S., Bugiani, R. (2008). A mechanistic model simulating primary
  infections of downy mildew in grapevine. *Ecological Modelling*, 212, 480–491.
- Tonietto, J., Carbonneau, A. (2004). A multicriteria climatic classification system for
  grape-growing regions worldwide. *Agricultural and Forest Meteorology*, 124, 81–97.
- Winkler, A. J., Cook, J. A., Kliewer, W. M., Lider, L. A. (1974). *General Viticulture.*
  University of California Press, Berkeley.
- Zabadal, T. J., Dami, I. E., Goffinet, M. C., Martinson, T. E., Chien, M. L. (2007). *Winter
  injury to grapevines and methods of protection.* Michigan State University Extension
  Bulletin E2930. `[ověřit autory]`
- Zahumenský, I. (2004). *Guidelines on Quality Control Procedures for Data from Automatic
  Weather Stations.* World Meteorological Organization, Geneva.

---

## Příloha A — Stav před migrací (analýza 2026-10-05)

**Co projekt umí:** stahování exportů z portálu Seleniem se seznamem čidel z DotVVM viewmodelu
(`chrome_driver.py`); výpočet GDD, Huglinova indexu, počtu mrazových záznamů, rosného bodu
a tropických dnů/nocí do JSON (`vineyard_analyst.py`); publikační grafy jedné a dvou veličin
v cs/de (`one_variable_plot.py`, `two_variable_plot.py`); 7denní klouzavý průměr
(`rolling_stats.py`); animace hodnot na mapě (`generate_animation.py`); kontrola intervalu
vzorkování nad natvrdo vloženými daty (`sampl_freq_basic.py`).

**Silné stránky:** automatický seznam čidel z viewmodelu (nová čidla se stáhnou bez úprav);
věcně správné vzorce GDD a Huglin; `generate_animation.py` jako vzor (typy, logging, validace
konfigurace, `pathlib`); přihlašovací údaje mimo repozitář; polohy čidel v GPX.

**Slabé stránky:**
- tři formáty vstupu (XLSX po čidlech, ručně slučovaný `data.xlsx` s listy, CSV se středníky)
  a tři formáty ID čidla; seznam čidel ve 4 YAML + GPX;
- duplicitní a nekonzistentní konfigurace (2 YAML v kořeni, 2 v `config/`, nepoužité klíče);
  cesty závislé na pracovním adresáři, absolutní Windows cesty v `.env` a README;
- natvrdo URL portálu, názvy a timeouty ve scraperu, ačkoli README tvrdí opak;
- chyby: 3 skripty nejdou spustit pod Pythonem < 3.12 (vnořené uvozovky v f-stringu, README
  uvádí 3.8+); `vineyard_analyst.py` spouští pipeline při importu; `frost_events_count` počítá
  záznamy místo hodin; `save_results` nevytváří složku; scraper hlásí jako stažený i starý
  soubor, chytá jen `ValueError` a obsahuje placeholder URL; v animaci chybějící `f` u logů,
  nesprávná výjimka u `read_csv`, režim `png_frames` ukládá celou animaci pro každý snímek,
  podklad mapy se stahuje pro každý snímek;
- žádná kontrola kvality dat (mezery, duplicity, časová zóna, přechod kancelář → vinice);
- žádné testy, balíček ani CLI; dva téměř shodné skripty na grafy; README popisuje neexistující
  funkce; `requirements.txt` v UTF-16 s celým `pip freeze` (vč. nesouvisejícího balíčku
  `ffmpeg` a stažené verze numpy); `.gitignore` ignoroval `*.md`.
