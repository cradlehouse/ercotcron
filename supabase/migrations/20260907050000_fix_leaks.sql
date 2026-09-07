-- Sep 2026 review, items 1-3 + 11.
--
-- #1 get_bid_sheet returned EVERY book's valuations to any signed-in member;
--    the private-book filter lived in the browser (bids/page.tsx BOOK_HOLDER).
--    The mapping moves server-side: book_holders says which holder code owns a
--    private book, and the RPC returns a private book's rows only to callers
--    with an approved claim on that code. Market/Discovery stay member-public.
create table if not exists book_holders (
  book        text primary key,
  holder_code text not null
);
alter table book_holders enable row level security;
revoke all on book_holders from anon, authenticated;  -- definer-only
insert into book_holders (book, holder_code)
  values ('Saaico 2027 First', 'XSAAIC')
  on conflict (book) do nothing;

create or replace function get_bid_sheet()
returns jsonb language sql security definer set search_path = public as $$
  select jsonb_build_object(
    'valuations', coalesce((
      select jsonb_agg(to_jsonb(v)) from path_valuations v
       where v.book in ('Market', 'Discovery')
          or v.book in (select bh.book from book_holders bh
                          join user_holders uh on uh.holder_code = bh.holder_code
                         where uh.user_id = auth.uid()
                           and uh.status = 'approved')), '[]'::jsonb),
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

-- #2 artifacts was world-readable including ref/* research inputs. The web
--    only ever reads the four allow-listed page artifacts; ref/* is platform
--    input and goes definer/service-only.
drop policy if exists "artifacts readable" on artifacts;
create policy "artifacts readable" on artifacts
  for select using (name not like 'ref/%');

-- #3 the pre-lockdown one-argument claim_holder overload returned the
--    verification token to any caller. Prod no longer has it (verified
--    2026-09-07); this keeps a rebuilt environment from resurrecting it.
drop function if exists claim_holder(text);

-- #11 the live-position predicate (end_date >= now, start_date <= now) used
--     by My Book / counterparty book / product builder can't use the
--     composite (holder, source, sink, ...) index and seq-scans awards.
create index if not exists crr_awards_end_idx on crr_awards (end_date);
