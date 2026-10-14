# Pre-registration: the November 2026 weather outlook

**Registered:** 15 Oct 2026, before any November base rate was computed and
before November delivery. The git commit carrying this file is the timestamp.

**Freeze:** Friday 16 Oct 2026. Inputs are cut off on 15 Oct at 23:59 CT,
which includes CPC's 15 Oct monthly and seasonal outlooks.

**Scored:** on or after 7 Dec 2026, once ERA5 covers all of November.

The outlook sits beside the NOV 2026 paper bids (v1 frozen 14 Oct, v2 by
21 Oct, v3 by 31 Oct) and never changes them. It holds no bid limit, mark or
dollar figure. The NOV auction has already been bid. This is a physical
forecast to read beside the paper book once November settles, not an input
to it.

## Same rules as January, with three differences

All of the following are as in the [JAN 2027 pre-registration](2026-10-14-jan2027-weather-outlook.md),
including its 15 Oct W2 addendum:

- the data sources, all pinned;
- the demand-weighted four-city proxy and the wind proxy;
- the forecasts: F0 climatology, F1 ENSO-conditional, F2 primary (F1 shrunk
  toward F0 with 10 pseudo-years);
- scoring by Brier and RPS;
- the wind-proxy validity rule.

The differences:

1. **Training years** are Novembers 1991–2025, 35 years.
2. **ENSO conditioning** uses the OND ONI, the season centred on November,
   at ≥ 1.0. The number of qualifying years is reported in the frozen file.
3. **The wind-proxy check** runs over Oct–Nov 2024 and Oct–Nov 2025 against
   our SystemWide actuals.

## Events (November 2026, CT calendar days)

| Id | Event | Definition |
|---|---|---|
| E1 | Freeze day | proxy daily mean ≤ 32°F; also counted in buckets {0, 1–2, 3–5, 6+} |
| E2 | Severe cold | any day with proxy daily min ≤ 20°F |
| E3 | Freeze run | ≥ 3 consecutive E1 days |
| W1 | Wind lull | ≥ 3 consecutive days with proxy wind capacity factor < 0.15 |
| W2 | Stricter lull (secondary) | chosen by the W2 rule over the November training years |
| K1 | Cool spell (secondary) | ≥ 3 consecutive days with proxy daily mean ≤ *t*, *t* chosen as below |
| T1 | Late timing (secondary) | given any E1, the first falls on Nov 16–30 |

**How *t* is chosen for K1:** *t* is one of {35, 38, 41, 44, 47}°F. The value
whose base rate over the training Novembers is closest to 20% wins, and ties
go to the lower *t*. K1 exists because freezing days are rare in a Texas
November, so E1–E3 may carry little information. That is expected, and it
isn't a reason to change them.

## Prediction

**Primary:** F2's Brier score summed over E1–E3 and K1 is lower than F0's.

One November is one observation. It goes on the running record beside the
January outlook and carries no claim of skill.

## Freeze procedure

```bash
.venv/bin/python -m strategy.winter_outlook --outlook NOV2026 --freeze --cpc <transcribed CPC context>.json
```

This writes `docs/outlooks/NOV2026-weather-outlook.json`, which is refused
if it already exists. The SHA-256 is added below in the freeze commit.
Every outcome gets published.
