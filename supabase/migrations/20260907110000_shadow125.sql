-- Pre-registered margin experiment (Tim + the Sep 7 banding analysis):
-- September showed clears at 1.00-1.25x our published limits running 168%
-- (6 paths, 4 ahead) while 1.25-1.50x ran 73% — the discipline cliff may sit
-- at 1.25x, not 1.5x. Rather than change the published rule on six paths of
-- in-sample evidence, OCT gets a SHADOW variant frozen BEFORE its auction:
-- identical rows, limits at 1.25x the published reference (= value/1.2).
-- Scored side by side with the real sheet against the same results and
-- settlement; admin-only (excluded from the member scorecard below).
-- If the loosened rule wins out of sample, November changes with a receipt.
insert into sheet_snapshots
  (sheet, source, sink, time_of_use, hedge_type, book, tier,
   ref_limit, suggested_mw, typical, worth, cleared_basis)
select 'OCT2026Monthly-shadow125', source, sink, time_of_use, hedge_type, book, tier,
       round(ref_limit * 1.25, 4), suggested_mw, typical, worth, cleared_basis
  from sheet_snapshots
 where sheet = 'OCT2026Monthly'
   and not exists (select 1 from sheet_snapshots where sheet = 'OCT2026Monthly-shadow125');

-- Member scorecard never shows shadow experiments.
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
                from sheet_snapshots where sheet not like '%-shadow%' group by 1, 2) t), '[]'::jsonb),
    'rows', coalesce((
      select jsonb_agg(to_jsonb(r) order by r.sheet, r.tier, r.ref_limit desc)
        from (select sheet, source, sink, time_of_use, hedge_type, tier,
                     ref_limit, suggested_mw, clearing, filled, cost,
                     realized, pnl
                from sheet_snapshots
               where sheet not like '%-shadow%'
               order by sheet, tier, ref_limit desc
               limit 600) r), '[]'::jsonb))
  where has_active_plan();
$function$
;
