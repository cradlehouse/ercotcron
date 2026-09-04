-- Nine-seat review P0 #1: path_valuations — the paid product — was readable
-- by the anon key (policy `using (true)` to public). Anyone could download
-- the full valuation set with one unauthenticated HTTP GET.
--
-- Lockdown: no direct SELECT for web roles at all. The bid sheet reads
-- through get_bid_sheet(), a definer function that requires a signed-in
-- user and returns valuations + per-path offered MW (aggregated from the
-- latest ingested offer file) + active settlement points in one call.
-- Awards/offers/bids tables stay readable — they mirror public ERCOT data.
drop policy if exists path_valuations_read on path_valuations;
revoke select on path_valuations from anon, authenticated;

create or replace function get_bid_sheet()
returns jsonb language sql security definer set search_path = public as $$
  select jsonb_build_object(
    'valuations', coalesce((select jsonb_agg(to_jsonb(v)) from path_valuations v), '[]'::jsonb),
    'offered', coalesce((
      select jsonb_agg(jsonb_build_object(
        'source', o.source, 'sink', o.sink,
        'time_of_use', o.time_of_use, 'hedge_type', o.hedge_type, 'mw', o.mw))
      from (
        select source, sink, time_of_use, hedge_type, sum(mw) as mw
        from crr_offers
        where auction_name = (select max(auction_name) from crr_offers)
          and (source, sink, time_of_use, hedge_type) in
              (select source, sink, time_of_use, hedge_type from path_valuations)
        group by 1, 2, 3, 4
      ) o), '[]'::jsonb),
    'offers_auction', (select max(auction_name) from crr_offers),
    'points', coalesce((
      select jsonb_agg(jsonb_build_object('name', name, 'active', active))
      from settlement_points), '[]'::jsonb)
  )
  where auth.uid() is not null;
$$;

revoke execute on function get_bid_sheet() from public, anon;
grant execute on function get_bid_sheet() to authenticated;
