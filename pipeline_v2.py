#!/usr/bin/env python3
"""4FGL-DR4 unassociated-source vetting pipeline (v2, fail-closed, resumable).

Bounty: DAiL bnty_0314 — "vet the unworked 4FGL sources". For every unassociated
4FGL-DR4 source we record four gates, each with the exact ADQL and the raw
response body it rests on:

  G1  WISE blazar-strip (WIBRaLS, J/ApJS/242/4/table3) counterpart inside the
      95% error ellipse (radius = amaj95).
  G2  chance probability from the local surface density of strip sources in an
      annulus (amaj95 .. 3*amaj95), p = 1 - exp(-rho * pi * r^2).
  G3  NVSS 1.4 GHz (VIII/65/nvss) within 2.5 arcmin: count + nearest flux.
  G4  VLASS Epoch 1 (J/ApJS/255/30/comp) within 2.5 arcmin: count + nearest Ftot.

Fail-closed: a gate counts as VERIFIED only when the TAP response parsed and
carried result rows (metadata present). An empty *catalog result* (metadata
present, zero data rows) is a valid scientific null and stays VERIFIED; a
network error / 4xx / unparseable body is UNVERIFIED and the row is not counted
as complete. That distinction is the whole point of the evidence rule.

Resumable: sources already present in evidence.jsonl are skipped, so a restart
never loses or redoes work.

Usage:
    python3 pipeline.py [--limit N] [--sleep S] [--out DIR]
"""
import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = "*"

TAP = "https://tapvizier.cds.unistra.fr/TAPVizieR/tap/sync"
FGL = "IX/72/4fgldr4"
STRIP = "J/ApJS/242/4/table3"
NVSS = "VIII/65/nvss"
VLASS = "J/ApJS/255/30/comp"
RADIO_RADIUS_DEG = 2.5 / 60.0  # 2.5 arcmin cone for both radio surveys


def tap(adql, timeout=120, tries=4):
    """Run one ADQL query. Returns dict with the query and the raw body, always."""
    url = TAP + "?" + urllib.parse.urlencode(
        {"REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "json", "QUERY": adql})
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as x:
                body = x.read().decode("utf-8", "replace")
            return {"adql": adql, "http": 200, "body": body}
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"  # 4xx = query is wrong; retrying will not help
            if 400 <= e.code < 500:
                break
        except Exception as e:
            err = str(e)[:200]
        time.sleep(2 + 2 * i)
    return {"adql": adql, "http": None, "body": "", "error": err}


def parse(res):
    """(names, rows). names is None when the body is missing/unparseable."""
    if not res.get("body"):
        return None, []
    try:
        d = json.loads(res["body"])
        names = [m.get("name") for m in d.get("metadata", [])]
        if not names:
            return None, []
        return names, d.get("data", []) or []
    except Exception:
        return None, []


def rows_as_dicts(res):
    names, data = parse(res)
    if names is None:
        return None
    return [dict(zip(names, r)) for r in data]


def sep_arcmin(ra1, de1, ra2, de2):
    r = math.pi / 180.0
    d = (math.sin(de1 * r) * math.sin(de2 * r)
         + math.cos(de1 * r) * math.cos(de2 * r) * math.cos((ra1 - ra2) * r))
    return math.degrees(math.acos(max(-1.0, min(1.0, d)))) * 60.0


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_done(path):
    done = set()
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["source"])
                except Exception:
                    continue
    return done


def sources(limit):
    adql = ('SELECT "4FGL",RAJ2000,DEJ2000,amaj95,bmin95,PA95,Sig,F1000 '
            f'FROM "{FGL}" WHERE Assoc1 = \' \' ORDER BY "4FGL"')
    res = tap(adql, timeout=180)
    rows = rows_as_dicts(res)
    if rows is None:
        print(json.dumps({"fatal": "source list query failed", "adql": adql,
                          "error": res.get("error")}))
        sys.exit(3)
    out = []
    for r in rows:
        name = str(r.get("4FGL") or "").strip()
        ra, de = num(r.get("RAJ2000")), num(r.get("DEJ2000"))
        if not name or ra is None or de is None:
            continue
        out.append({"source": name, "ra": ra, "dec": de,
                    "amaj95": num(r.get("amaj95")), "bmin95": num(r.get("bmin95")),
                    "pa95": num(r.get("PA95")), "sig": num(r.get("Sig")),
                    "f1000": num(r.get("F1000"))})
    return out[:limit] if limit else out


def gate_strip(src):
    ra, de = src["ra"], src["dec"]
    rad = max(src["amaj95"] or 0.1, 0.01)  # deg; never smaller than 0.6 arcmin
    adql = (f'SELECT TOP 50 WISE,RAJ2000,DEJ2000,"W1-W2",Class,Type,Radio,S,q22 '
            f'FROM "{STRIP}" WHERE 1=CONTAINS(POINT(\'ICRS\',RAJ2000,DEJ2000),'
            f'CIRCLE(\'ICRS\',{ra:.6f},{de:.6f},{rad:.6f}))')
    res = tap(adql)
    rs = rows_as_dicts(res)
    nearest = None
    if rs:
        seps = [sep_arcmin(ra, de, num(x["RAJ2000"]), num(x["DEJ2000"]))
                for x in rs if num(x.get("RAJ2000")) is not None]
        nearest = min(seps) if seps else None
    return {"verified": rs is not None, "count": None if rs is None else len(rs),
            "nearest_arcmin": nearest, "radius_deg": rad,
            "rows": (rs or [])[:5]}, res


def gate_density(src, rad):
    ra, de = src["ra"], src["dec"]
    adql = (f'SELECT COUNT(*) AS n FROM "{STRIP}" WHERE DISTANCE('
            f'POINT(\'ICRS\',RAJ2000,DEJ2000),POINT(\'ICRS\',{ra:.6f},{de:.6f})) '
            f'BETWEEN {rad:.6f} AND {3 * rad:.6f}')
    res = tap(adql)
    rs = rows_as_dicts(res)
    n = None
    if rs:
        n = num(list(rs[0].values())[0])
    rho = p = None
    if n is not None:
        area = math.pi * ((3 * rad) ** 2 - rad ** 2)
        rho = n / area if area > 0 else None
        if rho is not None:
            p = 1.0 - math.exp(-rho * math.pi * rad ** 2)
    return {"verified": rs is not None, "annulus_count": n,
            "local_density_per_deg2": rho, "p_chance": p}, res


def gate_radio(src, table, flux_cols):
    ra, de = src["ra"], src["dec"]
    adql = (f'SELECT TOP 20 * FROM "{table}" WHERE 1=CONTAINS('
            f'POINT(\'ICRS\',RAJ2000,DEJ2000),'
            f'CIRCLE(\'ICRS\',{ra:.6f},{de:.6f},{RADIO_RADIUS_DEG:.8f}))')
    res = tap(adql)
    rs = rows_as_dicts(res)
    nearest = None
    if rs:
        best = None
        for x in rs:
            s = sep_arcmin(ra, de, num(x["RAJ2000"]), num(x["DEJ2000"]))
            if best is None or s < best[0]:
                best = (s, x)
        if best:
            x = best[1]
            nearest = {"sep_arcmin": round(best[0], 3),
                       "id": str(x.get("NVSS") or x.get("CompName") or "")[:40]}
            for c in flux_cols:
                if c in x:
                    nearest["flux_mjy"] = num(x[c])
                    nearest["flux_col"] = c
                    break
    return {"verified": rs is not None, "count": None if rs is None else len(rs),
            "nearest": nearest, "rows": (rs or [])[:3]}, res


def vet(src, rawdir):
    g1, r1 = gate_strip(src)
    g2, r2 = gate_density(src, g1["radius_deg"])
    g3, r3 = gate_radio(src, NVSS, ["S1_4", "S1.4", "S"])
    g4, r4 = gate_radio(src, VLASS, ["Ftot", "Fpeak"])
    gates = {"G1_strip": g1, "G2_density": g2, "G3_nvss": g3, "G4_vlass": g4}
    complete = all(g["verified"] for g in gates.values())
    counterpart = bool(g1["count"] and (g1["nearest_arcmin"] or 99) <= 2.0)
    row = {
        "source": src["source"], "ra": src["ra"], "dec": src["dec"],
        "amaj95_deg": src["amaj95"], "bmin95_deg": src["bmin95"], "pa95_deg": src["pa95"],
        "signif": src["sig"], "f1000": src["f1000"],
        "gates": gates,
        "complete": complete,
        "strip_counterpart_within_2arcmin": counterpart,
        "raw": {"G1": r1, "G2": r2, "G3": r3, "G4": r4},
        "vet_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    safe = src["source"].replace(" ", "_").replace("/", "_")
    with open(os.path.join(rawdir, f"{safe}.json"), "w") as f:
        json.dump({k: row["raw"][k] for k in row["raw"]}, f)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = all unassociated sources")
    ap.add_argument("--sleep", type=float, default=0.4, help="seconds between sources")
    ap.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)))
    a = ap.parse_args()

    ev_path = os.path.join(a.out, "evidence.jsonl")
    rawdir = os.path.join(a.out, "raw")
    os.makedirs(rawdir, exist_ok=True)
    done = load_done(ev_path)
    srcs = sources(a.limit)
    todo = [s for s in srcs if s["source"] not in done]
    print(json.dumps({"total_unassociated": len(srcs), "already_done": len(done),
                      "todo": len(todo)}), flush=True)

    n_new = n_complete = n_counterpart = 0
    t0 = time.time()
    with open(ev_path, "a") as ev:
        for i, src in enumerate(todo, 1):
            try:
                row = vet(src, rawdir)
            except Exception as e:  # never let one source kill the batch
                row = {"source": src["source"], "ra": src["ra"], "dec": src["dec"],
                       "complete": False, "error": str(e)[:300],
                       "verdict_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            ev.write(json.dumps(row) + "\n")
            ev.flush()
            n_new += 1
            if row.get("complete"):
                n_complete += 1
            if row.get("strip_counterpart_within_2arcmin"):
                n_counterpart += 1
            if i % 25 == 0:
                rate = n_new / max(time.time() - t0, 1e-9)
                print(json.dumps({"done": n_new, "complete": n_complete,
                                  "counterparts": n_counterpart,
                                  "rate_per_min": round(rate * 60, 1)}), flush=True)
            time.sleep(a.sleep)
    summary = {"sources_processed": n_new, "complete": n_complete,
               "counterparts_within_2arcmin": n_counterpart,
               "seconds": round(time.time() - t0, 1)}
    json.dump(summary, open(os.path.join(a.out, "run_summary.json"), "w"), indent=1)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
