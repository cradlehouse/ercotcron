-- Pre-aggregate real-time to hourly, once.
--
-- The scanner views each re-joined dam_spp against raw rt_spp (7M rows and
-- growing toward 73M) and re-grouped it to hourly. Three views doing the same
-- expensive grouping is why none of them could build inside any statement
-- ceiling. Group once here; the others read ~260k pre-grouped rows.
--
-- WITH NO DATA for the same reason as the others: populating inside the
-- migration hits the runner's timeout. The signals job populates it first.

create materialized view if not exists rt_hourly as
select settlement_point,
       date_trunc('hour', interval_start) as hour_start,
       avg(price)  as price,
       min(price)  as price_min,
       max(price)  as price_max,
       count(*)    as intervals
  from rt_spp
 where interval_start >= now() - interval '400 days'
 group by 1, 2
with no data;

create unique index if not exists rt_hourly_key on rt_hourly (settlement_point, hour_start);
grant select on rt_hourly to anon, authenticated;
