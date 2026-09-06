-- The attribution layer: WHY a path paid or stopped paying, on settled data
-- only. Descriptive co-occurrence and dated public events — never a forecast.
--   wind:        the path's option payoff by system-wind tercile (last 12
--                settled months) — "does this path pay when the wind blows"
--   constraints: which DAM constraints were binding during the path's paid
--                hours (co-occurrence, not causation — labeled as such)
--   constraint_events: dated status changes for those constraints
--   energized:   new capacity at the endpoints or in their counties (public
--                energization records)
--   queued:      capacity in the interconnection queue for those counties,
--                by fuel, with earliest projected COD — public facts about
--                announced projects, not our prediction
-- The joins need real indexes: dam_constraints by delivery hour and
-- wind_power by region+hour — without them the 8s API statement timeout
-- kills the call.
create index if not exists dam_constraints_dh_idx
  on dam_constraints (delivery_date, hour_ending);
create index if not exists wind_power_rdh_idx
  on wind_power (region, delivery_date, hour_ending);

create or replace function get_path_attribution(p_src text, p_snk text)
returns jsonb language sql security definer
set search_path = public
set statement_timeout = '30s'
as $$
  with win as (
    select date_trunc('month', current_date)::date - interval '12 months' as lo,
           date_trunc('month', current_date)::date as hi
  ),
  hours as (
    select s.delivery_date, s.hour_ending, (k.price - s.price) as diff
      from dam_spp s
      join dam_spp k on k.interval_start = s.interval_start
     where s.settlement_point = p_src and k.settlement_point = p_snk
       and s.delivery_date >= (select lo from win)
       and s.delivery_date < (select hi from win)
  ),
  wind_h as (
    select h.diff, ntile(3) over (order by w.actual_mw) as tercile
      from hours h
      join wind_power w on w.delivery_date = h.delivery_date
                       and w.hour_ending = h.hour_ending
                       and w.region = 'SystemWide'
  ),
  wind_stats as (
    select tercile,
           round(avg(greatest(diff, 0))::numeric, 4) as avg_opt,
           round(sum(greatest(diff, 0))::numeric, 1) as paid_sum,
           count(*) as hrs
      from wind_h group by tercile
  ),
  paid as (
    select delivery_date, hour_ending, diff from hours where diff > 0.25
  ),
  topc as (
    select c.constraint_name,
           max(c.from_station) as from_station, max(c.to_station) as to_station,
           count(*) as hrs,
           round(avg(c.shadow_price)::numeric, 0) as avg_shadow
      from paid p
      join dam_constraints c on c.delivery_date = p.delivery_date
                            and c.hour_ending = p.hour_ending
     group by c.constraint_name
     order by count(*) desc
     limit 5
  ),
  counties as (
    select distinct county_ercot as county from node_attributes
     where settlement_point in (p_src, p_snk) and county_ercot is not null
  )
  select jsonb_build_object(
    'window', jsonb_build_object('from', (select lo from win), 'to', (select hi from win)),
    'data_through', jsonb_build_object(
      'constraints', (select max(delivery_date) from dam_constraints),
      'wind', (select max(delivery_date) from wind_power)),
    'paid_hours', (select count(*) from paid),
    'total_hours', (select count(*) from hours),
    'wind', coalesce((select jsonb_agg(jsonb_build_object(
              't', tercile, 'avg_opt', avg_opt, 'paid_sum', paid_sum, 'hours', hrs)
              order by tercile) from wind_stats), '[]'::jsonb),
    'constraints', coalesce((select jsonb_agg(jsonb_build_object(
              'name', constraint_name, 'from', from_station, 'to', to_station,
              'hours', hrs, 'avg_shadow', avg_shadow) order by hrs desc)
              from topc), '[]'::jsonb),
    'constraint_events', coalesce((select jsonb_agg(jsonb_build_object(
              'name', l.constraint_name, 'old', l.old_status, 'new', l.new_status,
              'reason', l.reason, 'at', l.changed_at::date) order by l.changed_at desc)
              from constraint_status_log l
             where l.constraint_name in (select constraint_name from topc)), '[]'::jsonb),
    'counties', coalesce((select jsonb_agg(county) from counties), '[]'::jsonb),
    'energized', coalesce((select jsonb_agg(jsonb_build_object(
              'point', e.settlement_point, 'project', e.project_name, 'fuel', e.fuel,
              'mw', e.capacity_mw, 'county', e.county, 'cod', e.cod,
              'at_endpoint', e.settlement_point in (p_src, p_snk)) order by e.cod desc)
              from node_energizations e
             where e.settlement_point in (p_src, p_snk)
                or e.county in (select county from counties)), '[]'::jsonb),
    'queued', coalesce((select jsonb_agg(jsonb_build_object(
              'fuel', fuel, 'mw', mw, 'projects', n, 'earliest_cod', cod) order by mw desc)
        from (select fuel, round(sum(capacity_mw)::numeric, 0) as mw,
                     count(*) as n, min(projected_cod) as cod
                from interconnection_queue
               where county in (select county from counties)
                 and coalesce(projected_cod, current_date) >= current_date
                 and coalesce(study_phase, '') not ilike '%cancel%'
               group by fuel) q), '[]'::jsonb)
  )
  where auth.uid() is not null;
$$;

revoke execute on function get_path_attribution(text, text) from public, anon;
grant execute on function get_path_attribution(text, text) to authenticated;
