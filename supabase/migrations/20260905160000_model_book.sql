-- "The model's book": the paper-trade rail becomes a visible track record.
-- Running mark-to-date columns (scoring columns — the append-only guard
-- already permits updating those; bid economics stay immutable) plus an
-- authenticated-only reader. Bids are OUR hypothetical picks, published
-- with the hypothetical-performance legend — a record, not a recommendation.
alter table paper_bids add column if not exists running_value numeric;  -- per-MW payoff banked so far (delivery in progress)
alter table paper_bids add column if not exists running_hours integer;  -- TOU hours banked in that figure
alter table paper_bids add column if not exists marked_through date;    -- last delivery day included

create or replace function get_model_book()
returns jsonb language sql security definer set search_path = public as $$
  select coalesce(jsonb_agg(to_jsonb(b) order by b.submitted_on desc, b.batch_id, b.bid_price desc), '[]'::jsonb)
  from (
    select batch_id, auction_name, submitted_at::date as submitted_on,
           source, sink, time_of_use, hedge_type, mw, bid_price,
           clearing_price, cleared, delivery_month,
           realized_value, pnl, running_value, running_hours, marked_through,
           scored_at::date as scored_on
      from paper_bids
  ) b
  where auth.uid() is not null;
$$;

revoke execute on function get_model_book() from public, anon;
grant execute on function get_model_book() to authenticated;
