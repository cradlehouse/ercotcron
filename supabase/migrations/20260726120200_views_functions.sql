-- Point-in-time read functions and operational views.

-- ------------------------------------------------------------ as-of reads --

-- The price for each interval as it stood at p_asof. A backtest that reads the
-- live tables instead will see values nobody could have known at trade time.
create or replace function rt_spp_asof(p_from timestamptz, p_to timestamptz, p_asof timestamptz)
returns table (settlement_point text, interval_start timestamptz, price numeric)
language sql stable as $$
  select distinct on (settlement_point, interval_start)
         settlement_point, interval_start, price
    from (
      select settlement_point, interval_start, price, price_from
        from rt_spp
       where interval_start >= p_from and interval_start < p_to
         and price_from <= p_asof and ingested_at <= p_asof
      union all
      select settlement_point, interval_start, price, price_from
        from rt_spp_history
       where interval_start >= p_from and interval_start < p_to
         and price_from <= p_asof and price_to > p_asof
    ) v
   order by settlement_point, interval_start, price_from desc;
$$;

create or replace function dam_spp_asof(p_from timestamptz, p_to timestamptz, p_asof timestamptz)
returns table (settlement_point text, interval_start timestamptz, price numeric)
language sql stable as $$
  select distinct on (settlement_point, interval_start)
         settlement_point, interval_start, price
    from (
      select settlement_point, interval_start, price, price_from
        from dam_spp
       where interval_start >= p_from and interval_start < p_to
         and price_from <= p_asof and ingested_at <= p_asof
      union all
      select settlement_point, interval_start, price, price_from
        from dam_spp_history
       where interval_start >= p_from and interval_start < p_to
         and price_from <= p_asof and price_to > p_asof
    ) v
   order by settlement_point, interval_start, price_from desc;
$$;

create or replace function lmp5_asof(p_from timestamptz, p_to timestamptz, p_asof timestamptz)
returns table (settlement_point text, interval_start timestamptz, price numeric)
language sql stable as $$
  select distinct on (settlement_point, interval_start)
         settlement_point, interval_start, price
    from (
      select settlement_point, interval_start, price, price_from
        from rt_lmp_5min
       where interval_start >= p_from and interval_start < p_to
         and price_from <= p_asof and ingested_at <= p_asof
      union all
      select settlement_point, interval_start, price, price_from
        from rt_lmp_5min_history
       where interval_start >= p_from and interval_start < p_to
         and price_from <= p_asof and price_to > p_asof
    ) v
   order by settlement_point, interval_start, price_from desc;
$$;

-- --------------------------------------------------------- health views --

-- Publication lag and revision volume by hour. Lag is measured from the end of
-- the interval, since a price cannot exist before its interval closes.
create or replace view feed_latency as
  select 'rt_spp'::text as feed,
         date_trunc('hour', interval_start) as hour,
         count(*)                           as rows,
         round(avg(extract(epoch from (ingested_at - (interval_start + interval '15 minutes'))))::numeric, 1) as avg_lag_seconds,
         max(ingested_at)                   as last_ingest
    from rt_spp
   where interval_start > now() - interval '7 days'
   group by 2
  union all
  select 'rt_lmp_5min',
         date_trunc('hour', interval_start),
         count(*),
         round(avg(extract(epoch from (ingested_at - (interval_start + interval '5 minutes'))))::numeric, 1),
         max(ingested_at)
    from rt_lmp_5min
   where interval_start > now() - interval '7 days'
   group by 2
  union all
  select 'dam_spp',
         date_trunc('hour', interval_start),
         count(*),
         null,
         max(ingested_at)
    from dam_spp
   where interval_start > now() - interval '7 days'
   group by 2;

create or replace view revision_counts as
  select 'rt_spp'::text as feed, date_trunc('hour', price_to) as hour, count(*) as revisions
    from rt_spp_history where price_to > now() - interval '7 days' group by 2
  union all
  select 'dam_spp', date_trunc('hour', price_to), count(*)
    from dam_spp_history where price_to > now() - interval '7 days' group by 2
  union all
  select 'rt_lmp_5min', date_trunc('hour', price_to), count(*)
    from rt_lmp_5min_history where price_to > now() - interval '7 days' group by 2;

-- Missing 15-minute intervals over the last three days, per settlement point.
-- The final interval is excluded: it may simply not be published yet.
create or replace view rt_spp_gaps as
  with points as (
    select distinct settlement_point from rt_spp
     where interval_start > now() - interval '3 days'
  ),
  slots as (
    select generate_series(
             date_trunc('hour', now() - interval '3 days'),
             date_trunc('hour', now()) - interval '30 minutes',
             interval '15 minutes') as interval_start
  )
  select p.settlement_point, s.interval_start
    from points p
    cross join slots s
    left join rt_spp r
      on r.settlement_point = p.settlement_point
     and r.interval_start   = s.interval_start
   where r.settlement_point is null
   order by s.interval_start desc, p.settlement_point;

-- The 15-minute SPP is a time-weighted average of the 5-minute SCED prices, so
-- averaging hides scarcity. spike_ratio is the within-interval peak over the
-- settled average — the number that tells you what the average concealed.
create or replace view spp_vs_lmp_5min as
  select s.settlement_point,
         s.interval_start,
         s.price                                as spp_15min,
         round(avg(l.price), 4)                 as lmp_5min_avg,
         max(l.price)                           as lmp_5min_max,
         min(l.price)                           as lmp_5min_min,
         count(l.price)                         as lmp_5min_count,
         case when s.price > 0
              then round(max(l.price) / s.price, 4)
         end                                    as spike_ratio
    from rt_spp s
    join rt_lmp_5min l
      on l.settlement_point = s.settlement_point
     and l.interval_start  >= s.interval_start
     and l.interval_start   < s.interval_start + interval '15 minutes'
   where s.interval_start > now() - interval '7 days'
   group by s.settlement_point, s.interval_start, s.price;

-- Latest price per settlement point, for the dashboard.
create or replace view latest_prices as
  select distinct on (settlement_point)
         settlement_point, interval_start, price, ingested_at
    from rt_spp
   where interval_start > now() - interval '1 day'
   order by settlement_point, interval_start desc;
