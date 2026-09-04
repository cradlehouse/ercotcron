-- Accuracy over ease (Tim's call): the scan computes a delivery-month-honest
-- "typical" payout (median of per-month means, capped by actual Septembers,
-- capped again by the recent three months) and was throwing it away at
-- publish — the UI then quoted the annual mean, which the July holdout
-- showed overstates a single month ~10x on spike paths. The ceilings were
-- already typical-derived; this column lets the DISPLAYED expectation be too.
alter table path_valuations add column if not exists value_typical numeric;
