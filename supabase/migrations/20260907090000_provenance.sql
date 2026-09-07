-- UI review #1: a provenance strip wherever a number appears. The data
-- mostly existed; nothing served it. One authenticated read returns the
-- freshest provenance for each surface: when valuations were computed and
-- over what window, when each sheet was frozen, how far settled prices run,
-- and the latest marks run (id / engine SHA / methodology version) once
-- marks.py starts logging runs.
create or replace function get_provenance()
returns jsonb language sql security definer set search_path = public as $$
  select jsonb_build_object(
    'valuations', (select jsonb_build_object(
        'computed_at', max(computed_at),
        'window_start', min(window_start),
        'window_end', max(window_end),
        'rows', count(*)) from path_valuations),
    'sheets', coalesce((select jsonb_agg(jsonb_build_object(
        'sheet', sheet, 'frozen_at', frozen, 'rows', n) order by sheet)
      from (select sheet, min(snapshot_at) frozen, count(*) n
              from sheet_snapshots group by 1) s), '[]'::jsonb),
    'data_through', (select max(delivery_date) from dam_spp),
    'mark_run', (select jsonb_build_object(
        'run_id', run_id, 'run_at', run_at, 'engine_sha', engine_sha,
        'methodology_v', methodology_v)
      from mark_runs order by run_at desc limit 1)
  )
  where auth.uid() is not null;
$$;
revoke execute on function get_provenance() from public, anon;
grant execute on function get_provenance() to authenticated;
