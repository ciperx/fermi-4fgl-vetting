# Batch results (live snapshot)

Snapshot: 2026-10-24T23:28:41.672412+00:00

- sources in evidence file: **146**
- complete (all 4 gates verified): **146** (100.00%)
- strip counterparts within 2 arcmin: **2**

A row is complete only when G1 (WISE blazar strip), G2 (local density / chance
probability), G3 (NVSS) and G4 (VLASS) each returned a parseable TAP response.
The raw ADQL and raw body for every gate are archived per source (not in this
repo snapshot to keep it small; they live in the run directory).

## Counterparts within 2 arcmin

| source | RA | Dec | sep (arcmin) | p_chance | NVSS | VLASS |
|---|---|---|---|---|---|---|
| J0004.4-4001 | 1.1184 | -40.0251 | 1.4437294635426394 | 0.0 | 1 | 3 |
| J0207.2-1832 | 31.8057 | -18.5437 | 0.9089207922341006 | 0.0 | 1 | 1 |

