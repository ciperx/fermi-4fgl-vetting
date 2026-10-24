# 4FGL-DR4 unassociated-source vetting pipeline

Fail-closed, resumable vetting of every unassociated source in the *Fermi* LAT
Fourth Source Catalog Data Release 4 (`4FGL-DR4`, VizieR `IX/72/4fgldr4`).

The point of this repository is **evidence, not verdicts**: every gate stores the
exact ADQL query and the raw TAP response body it rests on. A gate counts as
verified only when the response parsed and carried catalog metadata. A query that
errors, times out, or returns an unparseable body is `UNVERIFIED` and the source
is not counted as complete — even if the astrophysics would have been
interesting. An empty *result* (metadata present, zero data rows) is a valid
scientific null and stays verified.

## Gates

| gate | catalog | test |
|---|---|---|
| G1 strip counterpart | WISE blazar strip, `J/ApJS/242/4/table3` (WIBRaLS) | any strip source inside the 95% error ellipse (`radius = amaj95`) |
| G2 chance probability | same strip catalog | surface density ρ from the annulus `amaj95 … 3·amaj95`, `p = 1 − exp(−ρ·π·r²)` |
| G3 NVSS | `VIII/65/nvss` (1.4 GHz) | sources within 2.5 arcmin, nearest separation + flux `S1_4` |
| G4 VLASS | `J/ApJS/255/30/comp` (VLASS Epoch 1) | components within 2.5 arcmin, nearest separation + `Ftot` |

A source is `complete` only when all four gates are verified. The batch that
matters is the largest *complete* set: rows with a missing or failed gate are
kept in the output (so the failure is visible) but never counted.

## Source selection

Unassociated sources are selected with the catalog's own association column:

```sql
SELECT "4FGL", RAJ2000, DEJ2000, amaj95, bmin95, PA95, Sig, F1000
FROM "IX/72/4fgldr4"
WHERE Assoc1 = ' '
ORDER BY "4FGL"
```

That yields **2,423** sources out of 7,195 in DR4.

## Run

```sh
python3 pipeline_v2.py --sleep 0.4                 # all unassociated sources
python3 pipeline_v2.py --limit 50 --out /tmp/try   # smoke test
```

Outputs (in `--out`, default: script directory):

- `evidence.jsonl` — one JSON row per source: catalog position and 95% ellipse,
  all four gates with counts/separations/probabilities, `complete`, and the raw
  response for each gate.
- `raw/<source>.json` — the four raw TAP responses for that source, verbatim.
- `run_summary.json` — counts for the run.

The run is resumable: sources already present in `evidence.jsonl` are skipped, so
a restart never redoes or loses work.

## Notes on the queries

- `RING(...)` is rejected by the VizieR TAP service; the annulus uses
  `DISTANCE(POINT(...), POINT(...)) BETWEEN r1 AND r2` instead.
- `SELECT S1_4` alone returns HTTP 400 from this TAP endpoint even though the
  column is advertised in the table metadata; the radio gates therefore select
  `*` and read the flux column by name from the response metadata.
- `Sig`, not `Signif`, is the significance column in `IX/72/4fgldr4`.
- All HTTP calls strip proxy environment variables and set `NO_PROXY=*`: a
  transparent proxy that injects an HTML error page would otherwise be recorded
  as a catalog null, which is exactly the failure mode the evidence rule exists
  to prevent.

## License

Pipeline code: MIT. Catalog data belongs to the original survey teams (Fermi-LAT
collaboration, WISE/WIBRaLS, NVSS, VLASS) and is queried, not redistributed.
