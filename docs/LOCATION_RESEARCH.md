# Node location: what we have, what failed, and what is worth trying

Written 31 Jul 2026. Node location is the binding constraint on three things we
cannot otherwise do: attach local weather to a node, attribute new generation
or new load to a node, and reason about congestion geographically. Everything
else in this project works without it; those three do not.

## Current state

| tier | nodes | meaning |
|---|---|---|
| A | 41 | coordinates confirmed against ERCOT's own county |
| B | 176 | ERCOT county only — centroid, not a position |
| C | 370 | coordinates exist but cannot be verified either way |
| D | 440 | nothing |

614 of 1,027 have a county from some source. **Only 41 have a position anyone
should trade on.** Measured accuracy of the fuzzy-matched tier: 51% within 40km
of the correct county overall; 79% for the high-confidence subset. That is not
good enough for weather, where the whole point is that conditions differ across
tens of kilometres.

What IS solid: `settlement_point -> PSS/E bus` at 1,027/1,027, from ERCOT's own
`Settlement_Points` file. Every location approach should hang off that key
rather than off node names.

## Ruled out — do not retry

| source | outcome |
|---|---|
| ERCOT public API, all 107 products | **no coordinates anywhere.** Location is published only as zone/region membership. This is a design decision, not an oversight. |
| ERCOT contour/price maps | server-rendered heatmap images; no point data reaches the browser |
| HIFLD ArcGIS (old endpoints) | schema changed, returns nothing — worth ONE retry with current URLs, then drop |
| NP4-158-SG electrically-similar points | only 490 points, static across 2 months, +35 nodes |
| PSS/E graph harmonic interpolation | median 24km, p90 435km on holdout — no better than a county centroid |
| GIS report POI **name** matching | 0 joins. (The POI **bus number** works — see below — but the names do not.) |

## Confirmed working, already exploited

- **GIS report POI bus numbers** — 92% of interconnection projects carry a
  PSS/E bus number inside the POI Location string (`59903 Bearkat 345kV`).
  This is what produced the hybrid/battery technology tagging.
- **USGS USWTDB** — 19,464 Texas turbines, exact coordinates, project names.
  Median project footprint 11.5km, which is weather-coherent.
- **USGS USPVDB** — 187 Texas solar projects. Best-validated source at 88%
  within 40km.
- **EIA-860** — broad coverage but only 30% within 40km. Use as a last resort,
  not a primary.

## Worth trying, in priority order

### 1. Secured MIS — the CRR Network Model  *(highest value, now unblocked)*
Tim's ERCOT digital certificate was issued 28 Jul 2026. The secured MIS area
holds the network model used to clear CRR auctions, and any settlement-point
mapping ERCOT maintains internally. This is the authoritative answer and would
likely resolve the question outright rather than incrementally.
**Blocker:** requires certificate retrieval and install (Tim only — credential
handling). **Effort once in:** low. **Expected gain:** potentially all 1,027.

### 2. Texas PUC interconnection and CCN filings
Certificates of Convenience and Necessity for transmission lines and
substations are public filings that include **maps and route coordinates**.
Filed per project, so coverage builds up over years rather than arriving as one
table. Searchable via PUC Interchange.
**Effort:** high (per-filing parsing). **Expected gain:** substations, which is
the layer we are weakest on.

### 3. FERC Form 715
Annual transmission planning submissions include network models and one-line
diagrams for each planning region. Public with a lag.
**Effort:** medium. **Expected gain:** bus-level topology, possibly geographic.

### 4. Global Energy Monitor / OpenInfraMap
Both maintain open plant and infrastructure trackers with coordinates, built
independently of EIA. Cross-checking against them would at minimum let us
**validate tier C** — 370 nodes currently unverifiable in either direction,
which is the largest single block of uncertainty.
**Effort:** low. **Expected gain:** validation more than new coverage.

### 5. County appraisal district parcels
Generation and substation sites appear in property tax records with parcel
geometry. Texas CADs publish per-county, so this is 254 separate sources.
**Effort:** very high. **Use only** for specific high-value nodes, not sweeps.

### 6. Satellite/aerial imagery
Substation detection from imagery is a solved computer-vision problem and
several published models exist. Would give positions independent of any
registry.
**Effort:** very high. **Realistic only** if this becomes a core dependency.

## The honest fallback

If none of the above lands, the alternative is to stop trying to locate nodes
and instead work at the resolution ERCOT itself publishes: 8 weather zones, 6
wind regions, 7 solar regions. That is the resolution ERCOT's own market
clearing uses. It is too coarse to predict a single farm's output — but the
prices we are modelling are set off ERCOT's zonal forecasts, not off the true
local weather, so the coarse data is closer to the price-formation mechanism
than it first appears. This is a genuine strategic fork, not a consolation.

## Immediate next actions

1. Tim: retrieve and install the ERCOT digital certificate (5-day expiry from
   issue — check whether it has lapsed and needs reissue).
2. Retry HIFLD once against current ArcGIS endpoints.
3. Cross-check tier C against Global Energy Monitor / OpenInfraMap to convert
   "unverifiable" into "confirmed" or "wrong" — this is cheap and shrinks the
   uncertainty even without new coverage.
