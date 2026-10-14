"""Frozen month-ahead weather outlooks: JAN 2027 and NOV 2026. Rules in
docs/preregistrations/2026-10-14-jan2027-weather-outlook.md and
docs/preregistrations/2026-10-15-nov2026-weather-outlook.md.

Physical events only (cold days, outbreak runs, wind lulls). It never reads
or writes a bid limit, a mark or a sheet; it sits beside the JAN ticket.

  .venv/bin/python -m strategy.winter_outlook [--outlook NOV2026]   # dry run, prints
  .venv/bin/python -m strategy.winter_outlook --freeze --cpc F       # writes JSON + sha
  .venv/bin/python -m strategy.winter_outlook --score                # after the month

Sources: ERA5 via Open-Meteo's archive (pinned models=era5 so the series
never switches reanalysis mid-record), CPC ONI v5, and our own wind_power
actuals, used only to check the wind proxy.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import itertools
import json
import os
import pathlib
import statistics
import time

import httpx

from ercot.weather import SITES
from strategy.common import CACHE, ROOT

ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
TZ = "America/Chicago"


@dataclasses.dataclass(frozen=True)
class Spec:
    name: str
    month: int
    days: int
    target: int
    years: range
    oni_season: str          # the 3-month season centred on the target month
    check: tuple             # (start, end) windows for the wind-proxy check
    prereg: str
    cool_spell: bool = False  # K1 (November only)

    def window(self, year: int) -> tuple[str, str]:
        return f"{year}-{self.month:02d}-01", f"{year}-{self.month:02d}-{self.days}"

    def tag(self, year: int) -> str:
        # January keys predate the November outlook; kept so the cache is reused
        return str(year) if self.month == 1 else f"{year}-{self.month:02d}"

    @property
    def out(self) -> pathlib.Path:
        return ROOT / "docs" / "outlooks" / f"{self.name}-weather-outlook.json"


SPECS = {
    "JAN2027": Spec("JAN2027", 1, 31, 2027, range(1991, 2027), "DJF",
                    (("2024-12-01", "2025-02-28"), ("2025-12-01", "2026-02-28")),
                    "docs/preregistrations/2026-10-14-jan2027-weather-outlook.md"),
    "NOV2026": Spec("NOV2026", 11, 30, 2026, range(1991, 2026), "OND",
                    (("2024-10-01", "2024-11-30"), ("2025-10-01", "2025-11-30")),
                    "docs/preregistrations/2026-10-15-nov2026-weather-outlook.md",
                    cool_spell=True),
}

# Fixed, unvalidated demand-weighted proxy (registered; not ERCOT weather zones).
CITIES = {
    "DFW":         (32.78, -96.80, 0.35),
    "Houston":     (29.76, -95.37, 0.35),
    "Austin":      (30.27, -97.74, 0.15),
    "San Antonio": (29.42, -98.49, 0.15),
}
FREEZE_MEAN_F = 32.0     # E1: proxy daily mean at or below
SEVERE_MIN_F = 20.0      # E2: proxy daily min at or below
RUN_DAYS = 3             # E3 / W1 run length
LULL_CF = 0.15           # W1: proxy daily wind capacity factor below
ONI_CONDITION = 1.0      # F1 set: centred-season ONI at or above (moderate-or-stronger)
SHRINK_M = 10            # F2: pseudo-count toward climatology
WIND_VALID_R = 0.6       # W1 is scored only if the proxy tracks our actuals
E1_BUCKETS = [(0, 0), (1, 2), (3, 5), (6, 31)]
EVENTS = ["E1_any", "E2_any", "E3_run", "W1_lull", "W2_lull"]

# Secondary events fixed from the training years only (addenda of 14-15 Oct):
# the candidate whose base rate is closest to TARGET_RATE wins; ties go to
# the longer run, then the stricter threshold. Never refit on the target.
TARGET_RATE = 0.20
W2_GRID = [(d, cf) for d in (3, 4, 5) for cf in (0.05, 0.075, 0.10, 0.125)]
K1_GRID = [(3, t) for t in (35.0, 38.0, 41.0, 44.0, 47.0)]   # K1: run of days, mean <= t F


def _get(params: dict, cache_key: str) -> dict:
    path = CACHE / "winter_outlook" / f"{cache_key}.json"
    if path.exists():
        return json.loads(path.read_text())
    for attempt in range(5):
        resp = httpx.get(ARCHIVE_API, params={**params, "models": "era5", "timezone": TZ},
                         timeout=120)
        if resp.status_code == 429:
            time.sleep(30 * (attempt + 1))
            continue
        resp.raise_for_status()
        body = resp.json()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body))
        return body
    raise RuntimeError(f"archive throttled: {cache_key}")


def temps(spec: Spec, year: int) -> list[tuple[float, float]]:
    """Per day of the month: (weighted mean °F, weighted min °F)."""
    start, end = spec.window(year)
    per = []
    for name, (lat, lon, w) in CITIES.items():
        d = _get({"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
                  "daily": "temperature_2m_mean,temperature_2m_min",
                  "temperature_unit": "fahrenheit"}, f"t_{name}_{spec.tag(year)}")["daily"]
        per.append((w, d["temperature_2m_mean"], d["temperature_2m_min"]))
    days = []
    for i in range(spec.days):
        if any(m[i] is None or n[i] is None for _, m, n in per):
            raise ValueError(f"ERA5 gap in {spec.name[:3]} {year}, day {i + 1}")
        days.append((sum(w * m[i] for w, m, _ in per), sum(w * n[i] for w, _, n in per)))
    return days


def power_fraction(kmh: float) -> float:
    """Same generic curve as SQL wind_power_fraction(): cut-in 3, rated 12, cut-out 25 m/s."""
    ms = kmh / 3.6
    if ms < 3 or ms > 25:
        return 0.0
    return 1.0 if ms >= 12 else ((ms - 3) / 9.0) ** 3


def wind_cf(start: str, end: str, tag: str) -> dict[str, float]:
    """Daily proxy capacity factor: curve applied per site-hour, THEN averaged
    (power of the mean speed is not mean power). Equal site weights."""
    by_day: dict[str, list[float]] = {}
    for region, sites in SITES.items():
        for lat, lon in sites:
            h = _get({"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
                      "hourly": "wind_speed_100m"}, f"w_{region}_{lat}_{lon}_{tag}")["hourly"]
            for stamp, v in zip(h["time"], h["wind_speed_100m"]):
                if v is not None:
                    by_day.setdefault(stamp[:10], []).append(power_fraction(float(v)))
    n_sites = sum(len(s) for s in SITES.values())
    return {d: statistics.mean(v) for d, v in sorted(by_day.items()) if len(v) >= 24 * n_sites * 0.9}


def longest_run(flags: list[bool]) -> int:
    return max((len(list(g)) for k, g in itertools.groupby(flags) if k), default=0)


def daily(spec: Spec, year: int) -> dict:
    return {"year": year, "temps": temps(spec, year),
            "cf": list(wind_cf(*spec.window(year), spec.tag(year)).values())}


def lull(d: dict, run: int, cf: float) -> bool:
    return longest_run([c < cf for c in d["cf"]]) >= run


def cool(d: dict, run: int, t: float) -> bool:
    return longest_run([m <= t for m, _ in d["temps"]]) >= run


def choose(dailies: list[dict], grid: list, test) -> dict:
    """Pick a secondary threshold from training years only (see TARGET_RATE)."""
    def rate(g):
        return sum(test(d, *g) for d in dailies) / len(dailies)
    best = min(grid, key=lambda g: (abs(rate(g) - TARGET_RATE), -g[0], g[1]))
    return {"run_days": best[0], "threshold": best[1], "base_rate": round(rate(best), 3),
            "grid": {f"{g[0]}d<{g[1]}": round(rate(g), 3) for g in grid}}


def outcomes(d: dict, w2: dict, k1: dict | None) -> dict:
    days = d["temps"]
    e1 = [m <= FREEZE_MEAN_F for m, _ in days]
    first = next((i + 1 for i, f in enumerate(e1) if f), None)
    out = {
        "year": d["year"],
        "E1_days": sum(e1),
        "E1_any": any(e1),
        "E2_any": any(n <= SEVERE_MIN_F for _, n in days),
        "E3_run": longest_run(e1) >= RUN_DAYS,
        "W1_lull": lull(d, RUN_DAYS, LULL_CF),
        "W2_lull": lull(d, w2["run_days"], w2["threshold"]),
        "first_E1_day": first,
        "coldest_mean_f": round(min(m for m, _ in days), 1),
        "coldest_min_f": round(min(n for _, n in days), 1),
    }
    if k1:
        out["K1_cool_spell"] = cool(d, k1["run_days"], k1["threshold"])
    return out


def oni_table() -> list[tuple[str, int, float]]:
    """(season, year, anomaly) rows from CPC's v5 table, in file order."""
    rows = []
    for line in httpx.get(ONI_URL, timeout=60).text.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 4:
            rows.append((parts[0], int(parts[1]), float(parts[3])))
    return rows


def jeffreys(k: int, n: int) -> tuple[float, float, float]:
    """Point (k+.5)/(n+1) with a normal-approx 80% band — descriptive only."""
    p = (k + 0.5) / (n + 1)
    se = (p * (1 - p) / (n + 1)) ** 0.5
    return round(p, 3), round(max(0.0, p - 1.2816 * se), 3), round(min(1.0, p + 1.2816 * se), 3)


def shrink(p1: float, p0: float, n1: int) -> float:
    """F2: the smoothed ENSO rate pulled toward the smoothed climatology with
    SHRINK_M pseudo-years — always between them (addenda of 15 Oct)."""
    return round((n1 * p1 + SHRINK_M * p0) / (n1 + SHRINK_M), 3)


def forecast(history: list[dict], oni: dict[int, float], events: list[str]) -> dict:
    cond = [h for h in history if oni.get(h["year"], -9) >= ONI_CONDITION]
    recent = [h for h in history if h["year"] >= 2006]
    out = {"n_all": len(history), "n_enso": len(cond), "enso_years": [h["year"] for h in cond],
           "n_recent": len(recent), "events": {}, "E1_buckets": {}}
    for ev in events:
        f0 = jeffreys(sum(h[ev] for h in history), len(history))
        f1 = jeffreys(sum(h[ev] for h in cond), len(cond))
        out["events"][ev] = {
            "F0_climatology": f0,
            "F1_enso": f1,
            "F2_primary": shrink(f1[0], f0[0], len(cond)),
            "recent_2006_on": jeffreys(sum(h[ev] for h in recent), len(recent)),
        }
    for lo, hi in E1_BUCKETS:
        def share(rows):
            return (sum(lo <= h["E1_days"] <= hi for h in rows) + 0.5) / (len(rows) + len(E1_BUCKETS) * 0.5)
        p0, p1 = share(history), share(cond)
        out["E1_buckets"][f"{lo}-{hi}"] = {
            "F0_climatology": round(p0, 3), "F1_enso": round(p1, 3),
            "F2_primary": shrink(p1, p0, len(cond))}
    for col in ("F0_climatology", "F1_enso", "F2_primary"):   # renormalise smoothed buckets
        tot = sum(b[col] for b in out["E1_buckets"].values())
        for b in out["E1_buckets"].values():
            b[col] = round(b[col] / tot, 3)
    late = [h for h in cond if h["first_E1_day"]]
    # timing, from the ENSO-conditional set only
    out["T1_first_E1_after_15th_given_any"] = jeffreys(
        sum(h["first_E1_day"] > 15 for h in late), len(late))
    return out


def wind_proxy_check(spec: Spec) -> dict:
    """Daily proxy CF vs our SystemWide wind actuals over the spec's windows."""
    import psycopg
    proxy: dict[str, float] = {}
    actual: dict[str, float] = {}
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        cur = c.cursor()
        for start, end in spec.check:
            proxy.update(wind_cf(start, end, f"{start}_{end}"))
            cur.execute("""select delivery_date::text, avg(actual_mw) from wind_power
                            where region = 'SystemWide' and actual_mw is not null
                              and delivery_date between %s and %s
                            group by 1 having count(*) >= 22""", (start, end))
            actual.update({d: float(v) for d, v in cur.fetchall()})
    both = sorted(set(proxy) & set(actual))
    r = statistics.correlation([proxy[d] for d in both], [actual[d] for d in both])
    return {"days": len(both), "pearson_r": round(r, 3), "valid": r >= WIND_VALID_R}


def build(spec: Spec, cpc: dict | None = None) -> dict:
    table = oni_table()
    # centred-season ONI by target-month year
    oni = {y: a for season, y, a in table if season == spec.oni_season}
    dailies = [daily(spec, y) for y in spec.years]
    w2 = choose(dailies, W2_GRID, lull)
    k1 = choose(dailies, K1_GRID, cool) if spec.cool_spell else None
    history = [outcomes(d, w2, k1) for d in dailies]
    events = EVENTS + (["K1_cool_spell"] if k1 else [])
    return {
        "outlook": f"{spec.name} weather outlook",
        "preregistration": spec.prereg,
        "secondary_thresholds": {"W2_lull": w2, "K1_cool_spell": k1},
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "source": "ERA5 via archive-api.open-meteo.com (models=era5); CPC ONI v5",
        # the most recent season in the file, not the last DJF
        "latest_oni": dict(zip(("season", "year", "anomaly"), table[-1])),
        "forecast": forecast(history, oni, events),
        "wind_proxy_check": wind_proxy_check(spec),
        "history": history,
        # transcribed by hand at freeze (--cpc file), context only: no numeric
        # conversion into the probabilities above
        "cpc_context": cpc,
    }


def brier(p: float, hit: bool) -> float:
    return round((p - float(hit)) ** 2, 4)


def score(spec: Spec, frozen: dict) -> dict:
    # thresholds come from the frozen file, never refit
    th = frozen["secondary_thresholds"]
    obs = outcomes(daily(spec, spec.target), th["W2_lull"], th["K1_cool_spell"])
    f = frozen["forecast"]
    res = {"observed": obs, "retrieved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
           "brier": {}}
    for ev in f["events"]:
        if ev.startswith("W") and not frozen["wind_proxy_check"]["valid"]:
            continue
        e = f["events"][ev]
        res["brier"][ev] = {"F0": brier(e["F0_climatology"][0], obs[ev]),
                            "F1": brier(e["F1_enso"][0], obs[ev]),
                            "F2": brier(e["F2_primary"], obs[ev])}
    hit = next(k for k in f["E1_buckets"] if int(k.split("-")[0]) <= obs["E1_days"] <= int(k.split("-")[1]))
    res["E1_bucket_observed"] = hit
    for col, key in (("F0_climatology", "F0"), ("F1_enso", "F1"), ("F2_primary", "F2")):
        cum_p = cum_o = 0.0
        rps = 0.0
        for k, b in f["E1_buckets"].items():
            cum_p += b[col]
            cum_o += float(k == hit)
            rps += (cum_p - cum_o) ** 2
        res.setdefault("rps_E1_buckets", {})[key] = round(rps / (len(f["E1_buckets"]) - 1), 4)
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outlook", choices=sorted(SPECS), default="JAN2027")
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--cpc", help="JSON of hand-transcribed CPC releases (source, url, issued, text)")
    a = ap.parse_args()
    spec = SPECS[a.outlook]
    if a.score:
        print(json.dumps(score(spec, json.loads(spec.out.read_text())), indent=2))
        return
    cpc = json.loads(open(a.cpc).read()) if a.cpc else None
    if a.freeze and cpc is None:
        raise SystemExit("--freeze needs --cpc: the CPC context is part of what gets hashed")
    body = build(spec, cpc)
    text = json.dumps(body, indent=2, default=str) + "\n"
    if a.freeze:
        if spec.out.exists():
            raise SystemExit(f"{spec.out} exists — a frozen outlook is never rewritten")
        spec.out.parent.mkdir(parents=True, exist_ok=True)
        spec.out.write_text(text)
        print(f"frozen {spec.out}\nsha256 {hashlib.sha256(text.encode()).hexdigest()}")
    else:
        print(json.dumps({k: body[k] for k in ("secondary_thresholds", "forecast",
                                               "wind_proxy_check", "latest_oni")}, indent=2))


if __name__ == "__main__":
    main()
