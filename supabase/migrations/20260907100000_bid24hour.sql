-- The real clearing-price fix, replacing the same-day STANDARD-only mistake.
-- Ground truth from the raw auction files (verified against SEP2026Monthly,
-- 39,017 groups, zero exceptions):
--   * CRRType is a label: PREAWARD = BUY award, STANDARD = SELL award. Every
--     row is a real transaction of that auction; nothing is a restatement.
--   * Uniform price holds exactly per (path, TOU, hedge) among single-block
--     rows; buys and sells clear at the same price.
--   * Bid24Hour products carry ONE blended price stamped on all three TOU
--     rows — the only rows that pollute a TOU block's average.
-- So: capture the flag, and derive clears from single-block rows.
alter table crr_awards add column if not exists bid24hour boolean not null default false;
create index if not exists crr_awards_b24_idx on crr_awards (auction_name) where bid24hour;
