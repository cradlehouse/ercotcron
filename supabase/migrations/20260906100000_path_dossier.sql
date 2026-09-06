-- The path dossier: everything the platform knows about one path, in one
-- authenticated call. Descriptive only — same answer for every member.
--   awards:  what every auction (monthly AND long-term) charged for the path
--   payoffs: what the path actually paid per settled month, by TOU block
--            (same dow/hour TOU rule as the scorer; the methodology's known
--            2-7% holiday edge case applies here too)
--   offers:  the sell side — asks from holders shedding the path
--   valuations: our published stance (Market/Discovery books only — private
--            book rows stay behind the claim gate)
--   paper:   whether the model ever put this path on its own record
create or replace function get_path_dossier(p_src text, p_snk text)
returns jsonb language sql security definer set search_path = public as $$
  select jsonb_build_object(
    'awards', coalesce((
      select jsonb_agg(jsonb_build_object(
               'auction', auction, 'tou', tou, 'hedge', hedge, 'cp', cp,
               'mw', mw, 'holders', holders, 'start', s, 'end', e)
             order by s, auction)
        from (select auction_name auction, time_of_use tou, hedge_type hedge,
                     round(avg(clearing_price)::numeric, 4) cp,
                     round(sum(mw)::numeric, 1) mw,
                     count(distinct account_holder) holders,
                     min(start_date) s, max(end_date) e
                from crr_awards
               where source = p_src and sink = p_snk
               group by 1, 2, 3) a), '[]'::jsonb),
    'payoffs', coalesce((
      with hours as (
        select s.delivery_date, s.hour_ending,
               (k.price - s.price) as diff
          from dam_spp s
          join dam_spp k on k.interval_start = s.interval_start
         where s.settlement_point = p_src and k.settlement_point = p_snk
           and s.delivery_date >= (current_date - interval '25 months')
      )
      select jsonb_agg(jsonb_build_object(
               'm', m, 'tou', tou, 'obl', obl, 'opt', opt, 'hours', h)
             order by m) from (
        select to_char(delivery_date, 'YYYY-MM') m,
               case when hour_ending between 7 and 22
                    then case when extract(isodow from delivery_date) < 6
                              then 'PeakWD' else 'PeakWE' end
                    else 'Off-peak' end tou,
               round(avg(diff)::numeric, 4) obl,
               round(avg(greatest(diff, 0))::numeric, 4) opt,
               count(*) h
          from hours
         group by 1, 2
      ) g), '[]'::jsonb),
    'offers', coalesce((
      select jsonb_agg(jsonb_build_object(
               'auction', auction, 'tou', tou, 'hedge', hedge,
               'mw', mw, 'min_ask', ask) order by auction)
        from (select auction_name auction, time_of_use tou, hedge_type hedge,
                     round(sum(mw)::numeric, 1) mw,
                     round(min(min_price)::numeric, 4) ask
                from crr_offers
               where source = p_src and sink = p_snk
               group by 1, 2, 3) o), '[]'::jsonb),
    'valuations', coalesce((
      select jsonb_agg(to_jsonb(v))
        from (select book, time_of_use, hedge_type, value_mean, value_typical,
                     ceiling, cleared_price, trim_pct, warnings, window_end
                from path_valuations
               where source = p_src and sink = p_snk
                 and book in ('Market', 'Discovery')) v), '[]'::jsonb),
    'paper', coalesce((
      select jsonb_agg(jsonb_build_object(
               'batch', batch_id, 'auction', auction_name, 'tou', time_of_use,
               'hedge', hedge_type, 'mw', mw, 'bid', bid_price,
               'cleared', cleared, 'cp', clearing_price, 'pnl', pnl)
             order by submitted_at)
        from paper_bids
       where source = p_src and sink = p_snk), '[]'::jsonb)
  )
  where auth.uid() is not null;
$$;

revoke execute on function get_path_dossier(text, text) from public, anon;
grant execute on function get_path_dossier(text, text) to authenticated;
