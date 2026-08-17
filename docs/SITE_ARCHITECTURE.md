# Shadowprice — Platform Analysis & Ground-Up Rebuild Plan

**August 2026. Companion to PLAN.md (the business) and the two design looks
(Ledger / Dispatch — see the published design page).**

---

## 1. Complete inventory — what exists today

### Pages (grew organically as an ops tool; not yet a product)
| Route | What it is | Whose need | Verdict in rebuild |
|---|---|---|---|
| `/` | public landing (new) | acquisition | keep, reskin |
| `/signup` `/signin` `/app` | auth + member home (new) | both | keep, reskin, expand |
| `/bids` | THE bid sheet: ticket, budget allocator, CSV export | **Bidder** | promote to centerpiece of member area |
| `/map` | grid + relationship views, month/scope switches | both | fold into member area |
| `/monitor` (old `/`) | live price monitor | ops, weak product fit | demote to internal |
| `/paths` `/scanner` `/spikes` `/trades` `/why` `/health` | research/ops pages | internal | internal-only section |

### Engines & data (the real asset — 20+ tables, all append-only where it matters)
- Valuation: path_valuations, marks + mark_runs (immutable audit trail), holder marks
- Auction: crr_awards (48 auctions), crr_bids (anonymous BUY), crr_offers (SELL),
  paper_bids (immutable paper-trade rail)
- Constraints: dam_constraints (718k hrs), ruc_constraints, registry + novelty views
- Forward-looking feeds: transmission_projects, interconnection_queue,
  large_load_queue, model_change_notices
- Intelligence: market_intel + intel_impacts (provenance, expiry, append-only)
- Knowledge: negative_knowledge (the graveyard)
- Geo: node locations v3 (77A/382B/245C/323D), 7,155-edge topology, station coords
- Validation: settlement reconciliation (91%/2%), whole-market study (588k
  positions), physics-bound check (478/480)

### The mismatch the rebuild fixes
The platform is organized by **where data came from** (ops pages per feed).
The business sells **decisions to two customers**. Navigation, hierarchy, and
theme must be reorganized around the two jobs: *"what do I bid?"* and
*"what is it worth / prove it."*

## 2. The two users, and what each screen owes them

**Bidder** (small CRR shops; $250–750/mo): lives on a deadline cadence.
Needs: the next auction's sheet, his ticket, alerts on constraints behind his
paths, the map as context, the self-scored record as trust. Everything else
is noise to him.

**Valuer** (banks, auditors, wind-downs; episodic $15–75k + later $25k+/yr
monitoring): lives on a reporting cadence. Needs: a book's mark with
provenance, stale flags with reasons, exportable documents that look like
evidence, and the methodology one click away. Never needs a budget allocator.

## 3. New information architecture

```
PUBLIC                        MEMBER (/app shell, per-user auth)
/            landing         /app             Today: next auction countdown,
/scorecard   free monthly                      ticket status, alerts, record
             issues (+hashes) /app/sheet       THE bid sheet (from /bids)
/methodology the doc, HTML    /app/ticket      current ticket + CSV export
/record      self-scoring     /app/book        YOUR positions, marked (per-
             archive                           holder privacy rule enforced)
/signin /signup               /app/map         grid + relationships
                              /app/alerts      constraint alerts + intel feed
                              /app/settings    plan, billing (Stripe later)
INTERNAL (basic-auth /ops/*)  VALUER (report-shaped, Ledger-skinned always)
monitor, scanner, spikes,     /app/book/report   printable book valuation
paths, trades, why, health    (+ bespoke engagements delivered as documents)
```

Principles: member area is **job-first, not data-first**; per-holder data
only behind that holder's login; every number shows its run id; reports
always render in Ledger paper regardless of chosen app skin.

## 4. New data structures (created with this plan)

- **user_holders** — links an account to the CRRAH code(s) it may see
  (admin-granted; enforces the privacy rule at the DB).
- **watchlists** — per-user watched paths/constraints; drives alerts and
  the "your paths" cut of every screen.
- **alert_events + alert_deliveries** — when intel/novelty touches a watched
  entity: one row per event, one per delivery (email wiring next).
- **sheets** — published bid-sheet editions per auction (run id, status:
  draft → published → scored), so "the sheet" becomes a versioned artifact
  users open, not a page that silently changes.
- (existing profiles table carries plan/trial; Stripe fields added later.)

## 5. Rebuild sequencing (repaint starts on look choice)

1. **Theme tokens** — all colors become CSS variables; both looks defined;
   chosen look becomes default app skin, Ledger always used for documents.
2. **/app shell + nav** — the job-first IA above; move bids/map inside.
3. **/app/book** — per-user book view over user_holders (new page, engine
   exists).
4. **Alerts** — watchlists UI + event generation from intel/novelty.
5. **Public /scorecard + /methodology + /record** — the trust surface.
6. Internal pages regroup under /ops (unchanged, basic-auth).

Each step ships independently; nothing waits for a big-bang.
