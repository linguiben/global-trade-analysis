  -- 1) 看最近运行参数是否没开 force_regen
  select id, started_at, status, message, params
  from job_runs
  where job_id = 'generate_homepage_insights'
  order by id desc
  limit 5;

  -- 2) 看该 scope/card/tab 最近 insight（含 llm/template）
  select id, created_at, generated_by, data_digest, llm_error, input_snapshot_keys
  from widget_insights
  where card_key='trade_flow' and tab_key='corridors' and scope='global' and lang='en'
  order by id desc
  limit 10;

  -- 3) 看 trade_corridors 最新快照 id（用于对比 input_snapshot_keys 里的 snapshot_id）
  select id, fetched_at, source_updated_at
  from widget_snapshots
  where widget_key='trade_corridors' and scope='global'
  order by fetched_at desc
  limit 1;
 
  -- job_definitions
  select * from job_definitions jd  
  select * from app_user
select * from  public.user_visit_log
  
select min(to_char(fetched_at, 'YYYY-MM-DD')), max(fetched_at )
  from widget_snapshots
  where widget_key='trade_corridors' and scope='Global'
  order by fetched_at desc
  limit 1;

select to_char(fetched_at, 'YYYY-MM-DD')dt, count(1) from widget_snapshots group by to_char(fetched_at, 'YYYY-MM-DD')


-- 创建备份表（只复制最近7天数据）
CREATE TABLE widget_snapshots_backup (LIKE widget_snapshots INCLUDING ALL);
INSERT INTO widget_snapshots_backup SELECT * FROM widget_snapshots;

-- 验证
SELECT COUNT(*) FROM widget_snapshots_backup;  -- 检查数据量[web:22]
SELECT COUNT(*) FROM widget_snapshots;  -- 检查数据量[web:22]

select * from widget_snapshots where fetched_at >= '2026-02-19'


