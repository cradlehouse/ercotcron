-- The method score is MEMBER-visible, not admin-only: self-scoring our own
-- published rows is exactly what methodology §10 pre-registers, and the
-- brand is "scored in public". (Holder-protecting aggregation floors apply
-- to statistics about market participants — these rows are our own calls.)
create or replace function get_method_score()
returns jsonb language sql security definer set search_path = public as $$
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
                from sheet_snapshots group by 1, 2) t), '[]'::jsonb),
    'rows', coalesce((
      select jsonb_agg(to_jsonb(r) order by r.sheet, r.tier, r.ref_limit desc)
        from (select sheet, source, sink, time_of_use, hedge_type, tier,
                     ref_limit, suggested_mw, clearing, filled, cost,
                     realized, pnl
                from sheet_snapshots
               order by sheet, tier, ref_limit desc
               limit 600) r), '[]'::jsonb))
  where auth.uid() is not null;
$$;
