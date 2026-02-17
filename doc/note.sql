select * from user_visit_log limit 10;

select * from job_definitions

update 
job_definitions 
set cron_expr = '0 */8 * * *'
where cron_expr = '*/10 * * * *'


-- the latest job run for insights
select * from job_runs where job_id = 'generate_homepage_insights' order by id desc limit 10;
select * from insight_generate_logs order by id desc limit 10;
where card_key = 'wealth' and scope = 'Mexico' and tab_key = 'gdp_pc' order by id LIMIT 3

-- the detailed log for insights
select * from insight_generate_logs where card_key = 'wealth' and scope = 'Mexico' and tab_key = 'gdp_pc' order by id LIMIT 3
-- the content for the insights
select * from widget_insights where card_key = 'trade_flow' and scope = 'Global' and tab_key = 'corridors' and generated_by='llm' order by id LIMIT 1;
select * from widget_insights where card_key = 'wealth' and scope = 'Mexico' and tab_key = 'gdp_pc' and generated_by='llm' order by id LIMIT 1;


select distinct card_key, tab_key, "scope"  from widget_insights limit 100;

-- insights
select distinct tab_key from widget_insights where card_key = 'trade_flow' and scope = 'global' 
wci
portwatch
corridors
{"lang":"en","scope":"Mexico","card_key":"wealth","tab_key":"gdp_pc"}

select * from widget_commentaries limit 10
select * from widget_snapshots limit 10;
select * from widget_insight_job_state limit 10;
select * from 

