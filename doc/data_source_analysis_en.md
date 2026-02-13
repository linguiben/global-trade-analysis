# GTA Data Sources Acquisition & Display (Deep Research)

> Goal: Based on `doc/20260213需求分析.md`, build **implementable** data-source plans for each GTA module (prefer public / no-key sources), define a unified metadata contract (Source / Period / Definition / References), and provide a Roadmap + Commentary reference list.

---

## 1. Overall Principles (Data Fetching vs. Display)

1) **No direct calls from web pages to external sources**: use jobs to fetch → store to DB (WidgetSnapshot) → UI reads from DB. This avoids corporate network/browser blocking and external API instability.
2) **Every metric must be explainable**: UI must include Source (org/link) + Period (range/latest point) + Unit/Frequency + Caveats (proxy indicator / missing-data handling).
3) **Ranking/Top N impacts display only**: job side stores Top20/Top50; frontend truncates by TopN (5/10/20).
4) **Commentary must include citations**: if there is no publication reference, downgrade to “Data-only commentary (based on the data only)”.

---

## 2. Recommended Data Sources (by Module/Tab)

### 2.1 Global Trade Flow

#### A) Corridors (Value / Volume) & Ranking
**Current**: MVP / placeholder data.

**Recommended primary sources (priority order)**

1) **IMF PortWatch (public downloads + API links)**
   - Usage: near-real-time proxy for “port activity / trade-volume nowcast”, and for chokepoints monitoring (e.g., Suez/Panama).
   - Entry points:
     - Data & Methodology: <https://portwatch.imf.org/pages/data-and-methodology>
     - Dataset example (Daily Port Activity Data and Trade Estimates): <https://portwatch.imf.org/datasets/959214444157458aad969389b3ebe1a0_0/about>
     - Dataset example (Chokepoint Transit Calls and Trade Volume Estimates): <https://portwatch.imf.org/datasets/42132aa4e2fc4d41bdaf9a445f688931_0/about>
   - Frequency: daily (as stated on PortWatch pages).
   - Note: PortWatch is closer to a “port/shipping proxy” than customs statistics; suitable for **high-frequency monitoring** and Roadmap/Commentary citations.

2) **WTO API (official time-series indicators; may require registration / terms constraints)**
   - Usage: low-to-mid frequency official trade indicators; also as citation sources for Roadmap (policy/trends).
   - Entry: WTO API Developer Portal: <https://apiportal.wto.org/>
   - Frequency: monthly/quarterly/annual (depends on indicator).

3) **World Bank WITS API (aggregates UNCTAD/TRAINS etc.; API-friendly)**
   - Usage: trade stats / tariffs / NTM; can be a more rigorous base for corridor / directional trade, but implementation complexity is higher.
   - Entry: <https://wits.worldbank.org/witsapiintro.aspx?lang=en>
   - User guide: <https://wits.worldbank.org/data/public/WITSAPI_UserGuide.pdf>

**Implementation suggestions (Corridors Ranking)**
- Phase 1: keep current `trade_corridors` snapshot structure, extend to Top20/Top50:
  - `value_top[]`: `{origin, dest, value_usd, rank}`
  - `volume_top[]`: `{origin, dest, volume_kg, rank}`
- Phase 2: integrate PortWatch chokepoints / port calls as “corridor activity proxy”, and explicitly show caveats as proxy.

#### B) Export/Import/Balance (5Y)
**Recommended source**: World Bank WDI (no key, stable)
- API: `https://api.worldbank.org/v2/country/{ISO3}/indicator/{INDICATOR}?format=json&date=YYYY:YYYY&per_page=200`
- Indicators:
  - Export: `NE.EXP.GNFS.CD` (current US$)
  - Import: `NE.IMP.GNFS.CD` (current US$)
- Frequency: annual
- Caveat: WDI is lagged (often only up to last year).

#### C) Freight (WCI)
**Recommended source**: Drewry World Container Index (public webpage; scrape/parse)
- Entry (example): <https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry>
- Frequency: weekly (updated weekly on the page)
- Caveat: page structure can change; for more stability, consider alternatives (paid data / redistributed platforms) and mind licensing.

#### D) PortWatch (tab)
**Recommended source**: IMF PortWatch (same as above)
- In snapshot/UI, explicitly mark as nowcast/proxy, not final customs statistics.

---

### 2.2 Global Wealth Distribution

#### A) GDP per capita / Consumption (5Y)
**Recommended source**: World Bank WDI (no key, stable)
- GDP per capita: `NY.GDP.PCAP.CD` (current US$)
- Household final consumption expenditure: `NE.CON.PRVT.CD` (current US$)
- Frequency: annual

#### B) Disposable (pc / hh)
**Current**: pc uses WB proxy / or WPR + fallback; hh still missing.

**Suggested strategy**

1) **pc**: prioritize WB (no key) as proxy to avoid unstable scraping.
   - If you need a “closer-to-disposable” proxy, compare:
     - `NY.GNP.PCAP.CD` (GNI per capita)
     - `NE.CON.PRVT.PC.KD` (consumption per capita, constant)
   - Must clearly label it as proxy in `note/caveats`.

2) **hh (equivalised disposable income, USD, annual average FX)**:
   - **OECD SDMX (no key)** preferred; for uncovered economies, use national statistical offices or degrade to proxy.
   - Caveat: definitions of “equivalised” and availability vary across countries; definitions must be explicit.

#### C) Age Structure (ring chart)
**Recommended source**: World Bank WDI (no key, stable)
- Indicators (% of total population):
  - 0–14: `SP.POP.0014.TO.ZS`
  - 15–64: `SP.POP.1564.TO.ZS`
  - 65+: `SP.POP.65UP.TO.ZS`
- Frequency: annual
- Display: fits a ring chart (composition/share semantics).

---

### 2.3 Global Financial Flow (M&A by industry / country)

**Recommended source (implementable now)**: IMAA public statistics pages (existing implementation)
- Caveat: webpage structure may change; require caching + graceful fallback.

**Enhancement (later)**
- If more authoritative/API sources are required: evaluate OECD/World Bank/IMF FDI/M&A-related stats, but they typically are not “deal ranking” datasets; product semantics may change.

---

## 3. Snapshot Metadata Contract (Source & Period & References)

Recommend each WidgetSnapshot `payload` includes at least the following fields (keep the structure consistent even if some are empty):

```json
{
  "ok": true,
  "widget_key": "trade_exim_5y",
  "scope": "Global",
  "period": {
    "date": "2020:2024",
    "asof": "2026-02-13",
    "frequency": "annual"
  },
  "unit": "USD",
  "source": {
    "name": "World Bank WDI",
    "link": "https://api.worldbank.org/...",
    "license_note": "Attribution required; see provider terms"
  },
  "definitions": {
    "export": "NE.EXP.GNFS.CD (current US$)",
    "import": "NE.IMP.GNFS.CD (current US$)"
  },
  "caveats": ["Lagged official statistics; latest year may be t-1"],
  "references": [
    {"title": "WDI indicator page ...", "url": "...", "publisher": "World Bank", "date": "2026-01-28"}
  ],
  "data": {
    "series": [],
    "rows": []
  }
}
```

No need to refactor all payloads at once; you can incrementally add these fields in the jobs runner:
- `source/link/frequency/date/unit/definitions/caveats/references[]`
- Frontend Source & Definition blocks should depend only on these fields.

---

## 4. Roadmap (Global Trade narrative) — Suggested Reference List

Each Roadmap bullet should be bound to **one clickable publication**, and stored in `references[]`.

Recommended publication candidates (examples):

1) **WTO**: global trade stats/indicators and trade-policy updates
   - WTO statistics landing: <https://www.wto.org/statistics>
   - WTO API portal: <https://apiportal.wto.org/>

2) **UNCTAD**: Global Trade Update / trade & development insights
   - UNCTAD statistics hub: <https://unctad.org/statistics>
   - UNCTAD Data Hub: <https://unctadstat.unctad.org/EN/>

3) **IMF PortWatch (trade nowcast / chokepoints)**
   - Data & Methodology: <https://portwatch.imf.org/pages/data-and-methodology>

4) **World Bank (macro background indicators)**
   - WDI API / indicator pages as citations

5) **Drewry (shipping cost shocks)**
   - WCI page: <https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry>

Example Roadmap bullets (product-copy direction):
- China: export mix and destination re-allocation (cite WTO/UNCTAD stats/report)
- Red Sea / chokepoints: rerouting impact on freight cost and lead time (cite PortWatch chokepoints + Drewry WCI)
- US/EU trade policy: tariffs and compliance uncertainty (cite WTO policy/data pages)
- EM demand cycle: import demand recovery or weakening (cite WDI imports / UNCTAD trade updates)

---

## 5. Commentary (Deep Research + citations) — Implementation Suggestions

### 5.1 Source acquisition (implementable, low coupling)
- **Phase 1 (manually curated)**: keep 1–3 fixed references per tab (WTO/UNCTAD/IMF/Drewry/WB), with templated commentary.
- **Phase 2 (semi-automated)**:
  - jobs scrape publication pages (title/date/summary paragraph only)
  - LLM generates commentary (must write `references[]` alongside)
  - human review / sampling (avoid “unsupported inference”).

### 5.2 Storage
- `WidgetSnapshot.payload.references[]`: enforce writing on each generation
- Optional: add `commentary_version` and `commentary_updated_at` to control cadence (e.g., weekly updates).

### 5.3 Suggested update frequency
- High frequency (daily/weekly): PortWatch, WCI (good for automation)
- Low frequency (monthly/quarterly): WTO/UNCTAD reports (good for “fixed citations + weekly viewpoint updates”)

---

## 6. Licensing & Compliance (must be shown in UI)

- **World Bank WDI**: generally usable with attribution; show “World Bank WDI” with indicator/API links.
- **IMF PortWatch**: downloads/API usage follow site terms; show IMF/PortWatch link in Source block.
- **Drewry**: public page can be cited; automated scraping must respect terms and page-structure changes; keep link and label “public page scrape” in caveats.
- **WTO API**: may have developer terms / registration requirements; if enabled, label in docs and UI.

---

## 7. Next Implementation Checklist (Engineering tasks)

1) Incrementally enrich existing jobs payloads with `source/link/unit/frequency/period/definitions/caveats/references[]`.
2) Roadmap: start with static curated topics (5 themes + citations), then consider automated crawling.
3) Commentary: unify templates + minimal citation set first; then add semi-automated generation.
4) Ranking/Top N: store Top20/Top50 in jobs; frontend truncates for display.
