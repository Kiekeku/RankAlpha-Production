# Risk Nowcast (Macro & Regime Dashboard)

Risk Nowcast is computed and persisted in the database (nightly snapshots) and surfaced on the Home “Macro & Regime Dashboard”.

Canonical references (consolidated)
- Audit + lineage (persisted artifacts, inputs, cadence): `docs/DATA_CATALOG.md` (see “2.16 Risk Nowcast”)
- Exact formulas + thresholds (quant checklist): `docs/NOWCAST_QUANT_CHECKLIST.md`
- Home page inventory + UI → API → DB traceability: `macro.md`

Related references:

- Macro series catalog & symbol routing: `docs/macro_series.md`
- 1-page quant checklist (pillars + thresholds): `docs/NOWCAST_QUANT_CHECKLIST.md`
- DB schema inventory (tables/views used by macro endpoints): `docs/schemas.md`
- API endpoint notes (includes liquidity regime rule + vol-regime notes): `apps/api/README.md`
- Ingestion-side HY stress computation details: `apps/ingestion/README.md`
- Scorer-side VIX term structure + VRP computation details: `apps/scorer/README.md`
