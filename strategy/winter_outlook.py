"""Frozen January 2027 weather outlook — rules in
docs/preregistrations/2026-10-14-jan2027-weather-outlook.md.

Physical events only (cold days, outbreak runs, wind lulls). It never reads
or writes a bid limit, a mark or a sheet; it sits beside the JAN ticket.

  .venv/bin/python -m strategy.winter_outlook            # dry run, prints
  .venv/bin/python -m strategy.winter_outlook --freeze   # writes the JSON + sha
  .venv/bin/python -m strategy.winter_outlook --score    # after Feb 10 2027

Sources: ERA5 via Open-Meteo's archive (pinned models=era5 so the series
never switches reanalysis mid-record), CPC ONI v5, and our own wind_power
actuals, used only to check the wind proxy.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import itertools
import json
import os
import statistics
import time

import httpx

from ercot.weather import SITES
from strategy.common import CACHE, ROOT

ARCHIVE_API = "https://archive-api.open-meteo.com/v1/archive"
ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
TZ = "America/Chicago"
TARGET = 2027
YEARS = range(1991, 2027)          # Januaries 1991..2026; 2027 is the target
OUT = ROOT / "docs" / "outlooks" / "JAN2027-weather-outlook.json"

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
ONI_CONDITION = 1.0      # F1 set: DJF ONI at or above (moderate-or-stronger)
SHRINK_M = 10            # F2: pseudo-count toward climatology
WIND_VALID_R = 0.6       # W1 is scored only if the proxy tracks our actuals
E1_BUCKETS = [(0, 0), (1, 2), (3, 5), (6, 31)]
EVENTS = ["E1_any", "E2_any", "E3_run", "W1_lull"]


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


def january(year: int) -> tuple[str, str]:
    return f"{year}-01-01", f"{year}-01-31"


def temps(year: int) -> list[tuple[float, float]]:
    """Per January day: (weighted mean °F, weighted min °F). None if incomplete."""
    start, end = january(year)
    per = []
    for name, (lat, lon, w) in CITIES.items():
        d = _get({"latitude": lat, "longitude": lon, "start_date": start, "end_date": end,
                  "daily": "temperature_2m_mean,temperature_2m_min",
                  "temperature_unit": "fahrenheit"}, f"t_{name}_{year}")["daily"]
        per.append((w, d["temperature_2m_mean"], d["temperature_2m_min"]))
    days = []
    for i in range(31):
        if any(m[i] is None or n[i] is None for _, m, n in per):
            raise ValueError(f"ERA5 gap in January {year}, day {i + 1}")
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


def outcomes(year: int) -> dict:
    days = temps(year)
    e1 = [m <= FREEZE_MEAN_F for m, _ in days]
    cf = list(wind_cf(*january(year), str(year)).values())
    first = next((i + 1 for i, f in enumerate(e1) if f), None)
    return {
        "year": year,
        "E1_days": sum(e1),
        "E1_any": any(e1),
        "E2_any": any(n <= SEVERE_MIN_F for _, n in days),
        "E3_run": longest_run(e1) >= RUN_DAYS,
        "W1_lull": longest_run([c < LULL_CF for c in cf]) >= RUN_DAYS,
        "first_E1_day": first,
        "coldest_mean_f": round(min(m for m, _ in days), 1),
        "coldest_min_f": round(min(n for _, n in days), 1),
    }


def oni_djf() -> dict[int, float]:
    """DJF ONI by January year, from CPC's v5 table."""
    out = {}
    for line in httpx.get(ONI_URL, timeout=60).text.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 4 and parts[0] == "DJF":
            out[int(parts[1])] = float(parts[3])
    return out


def jeffreys(k: int, n: int) -> tuple[float, float, float]:
    """Point (k+.5)/(n+1) with a normal-approx 80% band — descriptive only."""
    p = (k + 0.5) / (n + 1)
    se = (p * (1 - p) / (n + 1)) ** 0.5
    return round(p, 3), round(max(0.0, p - 1.2816 * se), 3), round(min(1.0, p + 1.2816 * se), 3)


def forecast(history: list[dict], oni: dict[int, float]) -> dict:
    cond = [h for h in history if oni.get(h["year"], -9) >= ONI_CONDITION]
    recent = [h for h in history if h["year"] >= 2006]
    out = {"n_all": len(history), "n_enso": len(cond), "enso_years": [h["year"] for h in cond],
           "n_recent": len(recent), "events": {}, "E1_buckets": {}}
    for ev in EVENTS:
        k0, k1 = sum(h[ev] for h in history), sum(h[ev] for h in cond)
        p0 = (k0 + 0.5) / (len(history) + 1)
        out["events"][ev] = {
            "F0_climatology": jeffreys(k0, len(history)),
            "F1_enso": jeffreys(k1, len(cond)),
            "F2_primary": round((k1 + SHRINK_M * p0) / (len(cond) + SHRINK_M), 3),
            "recent_2006_2026": jeffreys(sum(h[ev] for h in recent), len(recent)),
        }
    for lo, hi in E1_BUCKETS:
        def share(rows):
            return (sum(lo <= h["E1_days"] <= hi for h in rows) + 0.5) / (len(rows) + len(E1_BUCKETS) * 0.5)
        p0, p1 = share(history), share(cond)
        out["E1_buckets"][f"{lo}-{hi}"] = {
            "F0_climatology": round(p0, 3), "F1_enso": round(p1, 3),
            "F2_primary": round((p1 * len(cond) + SHRINK_M * p0) / (len(cond) + SHRINK_M), 3)}
    for col in ("F0_climatology", "F1_enso", "F2_primary"):   # renormalise smoothed buckets
        tot = sum(b[col] for b in out["E1_buckets"].values())
        for b in out["E1_buckets"].values():
            b[col] = round(b[col] / tot, 3)
    late = [h for h in cond if h["first_E1_day"]]
    # timing, from the ENSO-conditional set only
    out["T1_first_E1_after_15th_given_any"] = jeffreys(
        sum(h["first_E1_day"] > 15 for h in late), len(late))
    return out


def wind_proxy_check() -> dict:
    """Daily proxy CF vs our SystemWide wind actuals, Dec 2024 - Feb 2026."""
    import psycopg
    proxy: dict[str, float] = {}
    for start, end in [("2024-12-01", "2025-02-28"), ("2025-12-01", "2026-02-28")]:
        proxy.update(wind_cf(start, end, f"{start}_{end}"))
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        cur = c.cursor()
        cur.execute("""select delivery_date::text, avg(actual_mw) from wind_power
                        where region = 'SystemWide' and actual_mw is not null
                          and (delivery_date between '2024-12-01' and '2025-02-28'
                            or delivery_date between '2025-12-01' and '2026-02-28')
                        group by 1 having count(*) >= 22""")
        actual = {d: float(v) for d, v in cur.fetchall()}
    both = sorted(set(proxy) & set(actual))
    r = statistics.correlation([proxy[d] for d in both], [actual[d] for d in both])
    return {"days": len(both), "pearson_r": round(r, 3), "valid": r >= WIND_VALID_R}


def build(cpc: dict | None = None) -> dict:
    oni = oni_djf()
    history = [outcomes(y) for y in YEARS]
    return {
        "outlook": "JAN2027 weather outlook",
        "preregistration": "docs/preregistrations/2026-10-14-jan2027-weather-outlook.md",
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "source": "ERA5 via archive-api.open-meteo.com (models=era5); CPC ONI v5",
        "latest_oni": {k: v for k, v in sorted(oni.items())[-1:]},
        "forecast": forecast(history, oni),
        "wind_proxy_check": wind_proxy_check(),
        "history": history,
        # transcribed by hand at freeze (--cpc file), context only: no numeric
        # conversion into the probabilities above
        "cpc_context": cpc,
    }


def brier(p: float, hit: bool) -> float:
    return round((p - float(hit)) ** 2, 4)


def score(frozen: dict) -> dict:
    obs = outcomes(TARGET)
    f = frozen["forecast"]
    res = {"observed": obs, "retrieved_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
           "brier": {}}
    for ev in EVENTS:
        if ev == "W1_lull" and not frozen["wind_proxy_check"]["valid"]:
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
    ap.add_argument("--freeze", action="store_true")
    ap.add_argument("--score", action="store_true")
    ap.add_argument("--cpc", help="JSON of hand-transcribed CPC releases (source, url, issued, text)")
    a = ap.parse_args()
    if a.score:
        print(json.dumps(score(json.loads(OUT.read_text())), indent=2))
        return
    cpc = json.loads(open(a.cpc).read()) if a.cpc else None
    if a.freeze and cpc is None:
        raise SystemExit("--freeze needs --cpc: the CPC context is part of what gets hashed")
    body = build(cpc)
    text = json.dumps(body, indent=2, default=str) + "\n"
    if a.freeze:
        if OUT.exists():
            raise SystemExit(f"{OUT} exists — a frozen outlook is never rewritten")
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text)
        print(f"frozen {OUT}\nsha256 {hashlib.sha256(text.encode()).hexdigest()}")
    else:
        print(json.dumps({k: body[k] for k in ("forecast", "wind_proxy_check", "latest_oni")}, indent=2))


if __name__ == "__main__":
    main()
