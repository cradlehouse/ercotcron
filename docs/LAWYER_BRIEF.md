# Counsel Brief — Shadowprice (pre-publication review)

**Client:** Tim Capper, founder, Shadowprice (shadowprice.io) — sole founder,
Texas-based, pre-revenue. **Ask:** a scoped review (est. 1–3 hours) of planned
publications and product language before public launch, plus advice on
liability posture and insurance.

## What the business is

An analytics subscription for ERCOT Congestion Revenue Rights (CRRs).
Products, live today behind sign-up:

1. **Auction bid sheets** — before each ERCOT CRR auction, suggested bid
   limit prices per path derived from historical settlement data, with
   disclosed margin rules. Subscribers (small trading shops) decide and bid
   themselves through ERCOT's own systems. ~$250–750/mo.
2. **Holder book views** — a CRR account holder sees their *own* positions
   (public ERCOT award data) graded against our valuation scan. Access is
   verified against ERCOT's registered-contact records.
3. **Planned: a free monthly public "Scorecard"** — aggregate market
   statistics (e.g., "positions cleared above $5/MWh returned −13% as a
   class over 17 months"), no holder names, plus public self-scoring of our
   own prior sheets against actual auction and settlement results.
4. **Planned: episodic valuation engagements** — wind-down/exit valuations
   of CRR books, priced per engagement, based on *realized* (settled)
   payoff data.

**What we deliberately do NOT do** (standing internal policy, in writing):
no proprietary trading of CRRs or related products; no personalized
investment advice; no forward-value "attested" letters for financial
reporting (shelved on our own analysis); no marketplace/brokerage or
matching of buyers and sellers; no publication of named-holder performance;
per-holder data shown only to that verified holder.

## Facts counsel should know

- All input data is public (ERCOT publishes every auction award with holder
  identity, all settlement prices, constraint data). Our engine's outputs
  are reproducible from public data; methodology is a published, versioned
  document that discloses error rates (magnitude estimates land within 2× on
  ~61% of positions; directional accuracy ~96%).
- Every published number is stored append-only (database-enforced no-edit);
  each publication cites an immutable run ID.
- ERCOT is not FERC-jurisdictional, but our understanding is the CFTC's
  RTO/ISO exemption preserves CEA anti-fraud/anti-manipulation authority
  (§6(c)(1), Rule 180.1) and false-reporting liability (§9(a)(2)) over
  reports affecting commodity prices. We want that understanding checked.
- Precision on our accuracy stats: the ~96% figure is the constraint-
  exposure model's out-of-sample SIGN accuracy (predicted vs realized basis
  response) — not the accuracy of the bid sheets' picks, which will be
  scored publicly from the September auction on. Site copy is being
  corrected to say exactly that.
- One product fact counsel must weigh against our "no personalized advice"
  posture: the bid sheet includes an optional allocator ("Size the book for
  me") that converts a subscriber-entered budget and risk split into
  suggested MW per path, and verified holders see views personalized to
  their own positions. We are relabeling the allocator as neutral
  calculator arithmetic, but we want the analysis done on the real facts.
- Standard disclaimers currently on every surface: "not investment advice,"
  "not a forecast," "we hold no CRR positions," error rates stated.
- One design partner (a retiring CRR trader) supplies feedback and his own
  settlement statements for validation, with consent; he trades his own
  account independently of us and receives the same sheets subscribers do.

## Questions for the consult (priority order)

1. **Scorecard pre-publication review.** Does the draft public Scorecard
   (aggregate stats + self-scoring, attached) create exposure under Rule
   180.1 / §9(a)(2) or Texas law? What language changes, if any?
2. **Bid-sheet liability.** Subscribers act on suggested limit prices. Is
   our disclaimer set adequate? Do we need clickwrap terms of service with
   a liability cap before charging? (We have none yet — assume we need
   them; we'd like a lean template or referral.)
3. **Restatement §552 posture** for the *episodic* valuation engagements
   (realized-data wind-down valuations): engagement-letter liability caps,
   reliance limitations, and whether E&O insurance should precede the first
   engagement. Rough E&O sizing for a business this size.
4. **Publishing opinions on public data.** The credit-side product would
   show a *bank* the graded book of a counterparty (public positions, our
   grades) with the counterparty's knowledge but not consent — the
   rating-agency analogy. Green/yellow/red on that lane?
5. **Publisher posture vs the allocator and personalized holder views**
   (facts above): does either forfeit the impersonal-publisher exception
   under CTA/IA doctrine (Lowe; CFTC Rule 4.14), and are ERCOT CRRs
   "commodity interests" at all post-exemption?
6. **Horizontal-competitor concern:** multiple competing bidders in the
   same auction receive identical suggested limit prices ("enter the shown
   price and never more"). Does distributing uniform limits to horizontal
   competitors raise information-sharing / auction-manipulation questions,
   and are guardrails (language or subscriber mix) needed?
7. **Outreach lane:** planned one-time cold emails to contacts on ERCOT's
   public CRRAH registry (tool + published record, never the recipient's
   own graded positions), and an opt-in monthly Scorecard. CAN-SPAM
   requirements for the cold sends; whether our privacy policy's "where
   lawful, relevant correspondence" clause is an adequate disclosed basis
   for emailing non-users; confirm TCPA is out of scope absent texting.
8. **Anything we're not asking** that a commodities/publication lawyer sees
   immediately in the attached materials.

## Attachments (all short)

- Methodology document (public, versioned) — MARK_METHODOLOGY.md
- Draft Scorecard issue #1 (pre-publication)
- Sample counterparty credit report (redacted)
- Landing page copy (shadowprice.io)
- Internal standing-rules list (neutral-path decision record)

## Not sought in this engagement

Entity formation, tax, IP/trademark, employment — out of scope for now.
The single gating deliverable: a yes/no/with-changes on publishing
Scorecard issue #1, which is currently blocked only on this review.
