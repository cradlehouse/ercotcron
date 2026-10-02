-- Shadow experiments stay off the member scorecard: '%shadow%' names AND
-- the fade detector's removals ('*-faded', first frozen NOV2026Monthly-faded).
-- Row cap 600 -> 2000: with NOV frozen, a 600 cap sorted by sheet name
-- would cut the October rows members are watching settle.
CREATE OR REPLACE FUNCTION public.get_method_score()
 RETURNS jsonb
 LANGUAGE sql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select jsonb_build_object(
    'sheets', coalesce((
      select jsonb_agg(jsonb_build_object(
               'sheet', sheet, 'tier', tier, 'rows', n, 'snapshot_at', snap,
               'filled', filled_n, 'cost', cost, 'realized', realized, 'pnl', pnl)
             order by sheet, tier)
        from (select sheet, tier, count(*) n, min(snapshot_at)::date snap,
                     count(*) filter (where filled) filled_n,
                     round(sum(cost)::numeric, 0) cost,
                     round(sum(realized)::numeric, 0) realized,
                     round(sum(pnl)::numeric, 0) pnl
                from sheet_snapshots where sheet not like '%shadow%' and sheet not like '%-faded' group by 1, 2) t), '[]'::jsonb),
    'rows', coalesce((
      select jsonb_agg(to_jsonb(r) order by r.sheet, r.tier, r.ref_limit desc)
        from (select sheet, source, sink, time_of_use, hedge_type, tier,
                     ref_limit, suggested_mw, clearing, filled, cost,
                     realized, pnl
                from sheet_snapshots
               where sheet not like '%shadow%' and sheet not like '%-faded'
               order by sheet, tier, ref_limit desc
               limit 2000) r), '[]'::jsonb))
  where has_active_plan();
$function$
;
