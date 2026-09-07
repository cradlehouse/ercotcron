-- Day drill-down: one delivery day of a path, hour by hour, each hour tagged
-- with its TOU block so the UI can bunch them into the blocks you can
-- actually buy. CRRs settle on DAM hourly prices — there is no 15-minute
-- settlement for these instruments, so hourly is the finest honest grain.
-- Authenticated, like get_path_daily: prices are public ERCOT data.
create or replace function get_path_day(
  p_src text, p_snk text, p_tou text, p_hedge text, p_day date)
returns jsonb language sql security definer set search_path = public as $$
  select jsonb_build_object(
    'day', p_day,
    'tou', p_tou,
    'hours', coalesce((
      select jsonb_agg(jsonb_build_object(
               'he', he,
               'block', block,
               'collects', block = p_tou,
               'paid_per_mwh', round(paid::numeric, 2))
             order by he)
        from (
          select s.hour_ending as he,
                 crr_time_of_use(s.delivery_date, s.hour_ending) as block,
                 case when p_hedge = 'OPT'
                      then greatest(k.price - s.price, 0)
                      else k.price - s.price end as paid
            from dam_spp s
            join dam_spp k on k.interval_start = s.interval_start
           where s.settlement_point = p_src
             and k.settlement_point = p_snk
             and s.delivery_date = p_day
        ) t), '[]'::jsonb))
  where auth.uid() is not null;
$$;
revoke execute on function get_path_day(text, text, text, text, date) from public, anon;
grant execute on function get_path_day(text, text, text, text, date) to authenticated;
