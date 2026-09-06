#!/usr/bin/env python3
"""Render a frozen sheet snapshot into a self-contained HTML exhibit —
the as-published picture of what the sheet told people, preserved.

    python scripts/render_sheet.py OCT2026Monthly

Writes docs/sheets/<sheet>-published-<snapshot date>.html: the positive list
(green + amber reference limits with sizes and flags), the red don't-bid
list, provenance, and the required legends. Committed to the repo so the
record has a second, human-readable home outside the database.
"""
from __future__ import annotations

import datetime as dt
import os
import pathlib
import sys

from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
import psycopg  # noqa: E402

INK, PANEL, LINE, AMBER, MIST, BRIGHT = "#15242c", "#1e3038", "#2c424c", "#eda63a", "#93a6ab", "#f2f6f6"


def main() -> int:
    sheet = sys.argv[1] if len(sys.argv) > 1 else "OCT2026Monthly"
    with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=40) as c:
        cur = c.cursor()
        cur.execute("""
            select s.tier, s.source, s.sink, s.time_of_use, s.hedge_type,
                   s.ref_limit, s.suggested_mw, s.typical, s.worth,
                   s.cleared_basis, v.warnings, min(s.snapshot_at) over () as snap
              from sheet_snapshots s
              left join path_valuations v
                on v.source = s.source and v.sink = s.sink
               and v.time_of_use = s.time_of_use and v.hedge_type = s.hedge_type
               and v.book = s.book
             where s.sheet = %s
             order by case s.tier when 'green' then 0 when 'amber' then 1 else 2 end,
                      s.ref_limit desc nulls last""", (sheet,))
        rows = cur.fetchall()
    if not rows:
        print(f"no snapshot for {sheet}")
        return 1
    snap = rows[0][11]
    pos = [r for r in rows if r[0] in ("green", "amber")]
    red = [r for r in rows if r[0] == "red"]

    def money(v, dp=2):
        return f"${float(v):.{dp}f}" if v is not None else "—"

    def row_html(r):
        tier, src, snk, tou, hedge, ref, mw, typ, worth, clr, warn, _ = r
        tcol = {"green": "#34d399", "amber": AMBER, "red": "#f87171"}[tier]
        warn_html = f'<div style="color:{AMBER};opacity:.8;font-size:11px;margin-top:2px">{warn}</div>' if warn else ""
        return (f'<tr style="border-bottom:1px solid {LINE}55">'
                f'<td style="padding:6px 8px;color:{tcol};text-transform:uppercase;font-size:10px;letter-spacing:.06em">{tier}</td>'
                f'<td style="padding:6px 8px;font-family:ui-monospace,Menlo,monospace;font-size:12px;color:{BRIGHT}">{src} → {snk}{warn_html}</td>'
                f'<td style="padding:6px 8px;color:{MIST}">{tou} · {hedge}</td>'
                f'<td style="padding:6px 8px;text-align:right;font-family:ui-monospace,monospace">{money(ref)}</td>'
                f'<td style="padding:6px 8px;text-align:right;font-family:ui-monospace,monospace">{int(mw or 0)}</td>'
                f'<td style="padding:6px 8px;text-align:right;font-family:ui-monospace,monospace">{money(typ, 4) if typ is not None else money(worth, 4)}</td>'
                f'<td style="padding:6px 8px;text-align:right;font-family:ui-monospace,monospace">{money(clr, 4)}</td></tr>')

    head = (f'<tr style="border-bottom:1px solid {LINE};text-align:left;font-size:10px;'
            f'text-transform:uppercase;letter-spacing:.08em;color:{MIST}">'
            '<th style="padding:6px 8px">Tier</th><th style="padding:6px 8px">Path</th>'
            '<th style="padding:6px 8px">Block · type</th>'
            '<th style="padding:6px 8px;text-align:right">Reference limit</th>'
            '<th style="padding:6px 8px;text-align:right">Suggested MW</th>'
            '<th style="padding:6px 8px;text-align:right">Typical month $/MWh</th>'
            '<th style="padding:6px 8px;text-align:right">Usually clears</th></tr>')

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>{sheet} — as published</title></head>
<body style="margin:0;background:{INK};color:{BRIGHT};font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif">
<div style="max-width:1000px;margin:0 auto;padding:28px 20px">
  <div style="font-size:18px;font-weight:700"><span style="color:{AMBER}">shadow</span>price
    <span style="font-size:11px;color:{MIST};letter-spacing:.08em;text-transform:uppercase;margin-left:10px">the sheet, as published</span></div>
  <h1 style="font-size:19px;margin:18px 0 4px">{sheet}</h1>
  <div style="font-size:12px;color:{MIST}">frozen {snap:%Y-%m-%d %H:%M} UTC · {len(pos)} reference rows · {len(red)} don't-bid rows ·
    immutable snapshot (sheet_snapshots) · scored against results and settlement as they arrive</div>

  <h2 style="font-size:14px;margin:22px 0 6px">The positive list — reference limits</h2>
  <div style="background:{PANEL};border:1px solid {LINE};border-radius:8px;overflow:auto">
  <table style="width:100%;border-collapse:collapse;font-size:12.5px;min-width:860px">{head}
  {''.join(row_html(r) for r in pos)}
  </table></div>

  <h2 style="font-size:14px;margin:22px 0 6px">Don't bid — the red list</h2>
  <div style="background:{PANEL};border:1px solid {LINE};border-radius:8px;overflow:auto">
  <table style="width:100%;border-collapse:collapse;font-size:12.5px;min-width:860px">{head}
  {''.join(row_html(r) for r in red)}
  </table></div>

  <p style="font-size:11px;color:{MIST};line-height:1.6;max-width:95ch;margin-top:18px">
    Reference limits are the most our published margin rule supports — descriptions, not
    instructions; whether to bid, at what limit, and at what size is each reader's decision
    alone. Suggested MW are uniform liquidity-derived defaults, identical for every reader.
    Green = verified on real clearing history with no cautions; amber = positive on paper but
    unverified or flagged; red = the auction has charged more than the path returned.
    HYPOTHETICAL PERFORMANCE DISCLOSURE: sheet scoring is hypothetical — no actual bids are
    submitted and no positions held; hypothetical results do not reflect actual market
    participation, and no representation is made that any account will achieve similar
    results. All figures derive from public ERCOT data. Shadowprice holds no CRR positions.
  </p>
</div></body></html>"""

    outdir = ROOT / "docs" / "sheets"
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{sheet}-published-{snap:%Y-%m-%d}.html"
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size/1024:.0f} KB, {len(pos)} positive / {len(red)} red rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
