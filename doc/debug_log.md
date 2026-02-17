检查完 dashboard_v5_1 的数据链路。
- 页面入口：/gta/v5_1 -> homepage_v5_1 -> _dashboard_payload -> 模板 dashboard_v5_1.html  
  代码在 app/web/routes.py:287、app/web/routes.py:100、app/web/templates/dashboard_v5_1.html:495。
1) 数据保存在哪些数据库表？
主要是两张：
- widget_snapshots（页面主体数据）
  - trade/wealth/finance 各卡片数据都从这里读
  - 对应模型：app/db/models.py:78
  - 读取函数：get_latest_snapshot / get_latest_snapshots_by_key in app/jobs/runtime.py:1520, app/jobs/runtime.py:1529
- widget_insights（Insight 文本）
  - 对应模型：app/db/models.py:181
  - 页面组装时由 _latest_insights_map 读出：app/web/routes.py:74

辅助排查会用到：
- job_runs（任务执行时间、状态）app/db/models.py:52
- job_definitions（调度配置）app/db/models.py:28
- insight_generate_logs（洞察生成日志）app/db/models.py:146

2) 如何检查数据属于哪一年？
页面里“年份/时期”有几种来源，不是同一个字段：
- 页头 Data Updated：来自快照的 MAX(fetched_at)（最新抓取时间，不一定是经济数据年份）
- 贸易时间序列：看 widget_snapshots.payload->'series'[*].period
- Map 年份：/api/trade/exim-latest-all 返回 year（后端从每个 geo 最新 series.period 推导）
- Wealth/Trade 的 meta 通常显示 payload.date 或 payload.period
- 洞察卡片的 “Source updated” 来自 source_updated_at（有些源是推断、有些为空）

3) SQL：检查页面显示的数据范围和时间
下面是可直接跑的 PostgreSQL SQL（最实用的一组）：
-- A. 每个 widget_key + scope 的最新快照（页面实际读的就是这一类）
SELECT DISTINCT ON (widget_key, scope)
  id, widget_key, scope, fetched_at, source_updated_at, is_stale, source, payload
FROM widget_snapshots
ORDER BY widget_key, scope, fetched_at DESC;
-- B. 各模块时间范围（抓取时间 + 源数据时间）
SELECT
  widget_key,
  scope,
  COUNT(*) AS cnt,
  MIN(fetched_at) AS first_fetched_at,
  MAX(fetched_at) AS last_fetched_at,
  MIN(source_updated_at) AS first_source_updated_at,
  MAX(source_updated_at) AS last_source_updated_at
FROM widget_snapshots
WHERE widget_key IN (
  'trade_corridors',
  'trade_exim_5y',
  'wealth_indicators_5y',
  'wealth_disposable_latest',
  'wealth_age_structure_latest',
  'finance_ma_industry',
  'finance_ma_country'
)
GROUP BY widget_key, scope
ORDER BY widget_key, scope;
-- C. trade_exim_5y：取某个 scope 最新快照的 period 年份范围（页面图表年份核心）
WITH latest AS (
  SELECT payload
  FROM widget_snapshots
  WHERE widget_key = 'trade_exim_5y' AND scope = 'Global'
  ORDER BY fetched_at DESC
  LIMIT 1
)
SELECT
  MIN((x->>'period')::int) AS min_year,
  MAX((x->>'period')::int) AS max_year
FROM latest, LATERAL jsonb_array_elements(latest.payload->'series') x
WHERE (x->>'period') ~ '^\d{4}$';
-- D. wealth_indicators_5y：各 scope 的最新 period 年份范围
WITH latest AS (
  SELECT DISTINCT ON (scope) scope, payload
  FROM widget_snapshots
  WHERE widget_key = 'wealth_indicators_5y'
  ORDER BY scope, fetched_at DESC
)
SELECT
  l.scope,
  MIN((x->>'period')::int) AS min_year,
  MAX((x->>'period')::int) AS max_year
FROM latest l
CROSS JOIN LATERAL jsonb_array_elements(l.payload->'series') x
WHERE (x->>'period') ~ '^\d{4}$'
GROUP BY l.scope
ORDER BY l.scope;
-- E. 与页面头部 Data Updated 对齐（全局最新抓取时间）
SELECT MAX(fetched_at) AS dashboard_data_updated_at
FROM widget_snapshots
WHERE widget_key IN (
  'trade_corridors',
  'trade_exim_5y',
  'wealth_indicators_5y',
  'wealth_disposable_latest',
  'wealth_age_structure_latest',
  'finance_ma_industry',
  'finance_ma_country'
);
-- F. 页面 Insight 的最新时间（卡片右下 Source updated 对应数据）
SELECT
  card_key, tab_key, scope,
  created_at,
  source_updated_at
FROM widget_insights
WHERE generated_by = 'llm'
ORDER BY card_key, tab_key, scope, created_at DESC;

如果你要，我可以再给你一版“按页面分区（Trade/Wealth/Finance）汇总”的 SQL 报表，一次性输出“页面显示范围 + 最新年份 + 更新时间 + stale状态”。


Q: @app/web/templates/dashboard_v5_1.html "Global Trade Flow" - "Top 5 Countries by Export" 显示Singapore=978.6 bn USD, India=827.4 bn USD, 检查该值的来源，从哪个外部API获取，保存到数据库的哪个表哪个字段中。
A:
 总结如下：
   1. 数据来源: “出口前5名国家”的数据来源于世界银行WDI（世界发展指标）API。
   2. API端点: https://api.worldbank.org/v2/country/{country_code}/indicator/{indicator_code}
   3. 指标:
       * 出口: NE.EXP.GNFS.CD (商品和服务出口，现价美元)
       * 进口: NE.IMP.GNFS.CD (商品和服务进口，现价美元)
   4. 数据获取:
      数据由在app/jobs/runtime.py中定义的trade_exim_5y作业通过app/web/worldbank.py中的fetch_trade_exim
      _5y函数获取。
   5. 数据库存储: 获取的数据存储在widget_snapshots表中。
       * 表: widget_snapshots
       * 列:
           * widget_key: 值为'trade_exim_5y'。
           * scope: 值为国家名称（如'Singapore', 'India'）。
           * payload:
             一个JSONB列，包含进出口时间序列数据和元数据。具体的出口额存储在payload内series数组中的exp
             ort_usd键下。


  现在信息已经齐全，可以回答用户的问题了。我已经在app/jobs/runtime.py中找到了相关代码。


  作业trade_exim_5y的运行器是_run_trade_exim，它会为每个地区调用app/web/worldbank.py中的fetch_trade_ex
  im_5y函数，然后使用_record_snapshot将结果保存到数据库中。

  _record_snapshot函数会创建一个WidgetSnapshot对象并将其添加到数据库会话中。


  整个数据流程如下：
   1. 名为 trade_exim_5y 的计划作业会周期性运行。
   2. 该作业执行 _run_trade_exim 函数。
   3. 该函数从 app/web/worldbank.py 调用 fetch_trade_exim_5y，从世界银行WDI API获取出口
      (NE.EXP.GNFS.CD) 和进口 (NE.IMP.GNFS.CD) 数据。
   4. 获取的数据被存入数据库的 widget_snapshots 表中。
   5. Web应用从 widget_snapshots 表中读取数据以在仪表盘上显示。

  我已经收集了所有必要的信息，可以回答你的问题了。


  数据的来源、API和数据库存储信息总结如下：


   * 外部API: 数据来源于世界银行世界发展指标 (WDI) API。
       * 使用的具体指标是：
           * 出口: NE.EXP.GNFS.CD (商品和服务出口)
           * 进口: NE.IMP.GNFS.CD (商品和服务进口)
       * API调用逻辑位于 app/web/worldbank.py 文件中的 fetch_trade_exim_5y 函数。


   * 数据库表: 数据存储在 widget_snapshots 表中。
       * 该表的模型在 app/db/models.py 文件中定义。


   * 数据库字段:
       * widget_key: 存储作业的键，值为 'trade_exim_5y'。
       * scope: 存储国家/地区名称，例如 'Singapore' 或 'India'。
       * payload: 这是一个JSONB类型的字段，存储从世界银行API返回的完整时间序列数据，其中包含了多年的
         export_usd (出口额) 和 import_usd (进口额) 的值。

         {"ok": true, "geo": "Singapore", "date": "2021:2025", "errors": [], "series": [{"period": "2021", "export_usd": 797699635946.268, "import_usd": 639390598913.421, "balance_usd": 158309037032.84692}, {"period": "2022", "export_usd": 947354945030.236, "import_usd": 744363649815.365, "balance_usd": 202991295214.87097}, {"period": "2023", "export_usd": 917682665719.369, "import_usd": 728499583323.093, "balance_usd": 189183082396.276}, {"period": "2024", "export_usd": 978597520043.286, "import_usd": 786020626642.21, "balance_usd": 192576893401.07605}], "source": "World Bank WDI", "country": "SGP", "frequency": "annual"}

 > API端点: https://api.worldbank.org/v2/country/{country_code}/indicator/{indicator_code}
   调用该API时，country_code和indicator_code的值从来获取来？是hardcode还是从数据库中查询的?
▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄
✦ country_code 和 indicator_code 的值是这样获取的：


   1. `indicator_code` (指标代码):
       * 对于出口数据， indicator_code 硬编码为 "NE.EXP.GNFS.CD"。
       * 对于进口数据， indicator_code 硬编码为 "NE.IMP.GNFS.CD"。
       * 这些都是世界银行WDI（World Development Indicators）定义的特定指标代码。


   2. `country_code` (国家代码):
       * 在 app/jobs/runtime.py 文件中，有一个名为 GEO_TO_WDI
         的字典，它将仪表盘中使用的国家/地区名称（如 "Singapore"）映射到世界银行API所需的国家代码（如
         "SGP"）。
       * _run_trade_exim 函数会从作业参数 (params["geo_list"]) 中获取国家/地区名称列表，然后通过查找
         GEO_TO_WDI 字典来获取对应的 country_code。
       * params["geo_list"] 的默认值来自 trade_exim_5y 作业定义中的 default_params，它是一个硬编码的
         ALLOWED_GEOS 列表。


  因此，country_code 和 indicator_code 都不是从数据库中动态查询的。indicator_code 是硬编码的，而
  country_code 则是通过应用程序内部硬编码的映射 (GEO_TO_WDI 字典)
  从一个硬编码的国家/地区列表中获取的。

# 如何查找indicator_code？
> 1. World Bank 指标搜索页面 exports / imports / trade 等
> https://data.worldbank.org/indicator
> 2. API列出所有指标
> https://api.worldbank.org/v2/indicator
> 3. World Bank API 文档 https://datahelpdesk.worldbank.org/knowledgebase/articles/898599-indicator-api-queries?utm_source=chatgpt.com
示例:
```json
# 新加坡出口（占GDP）
https://api.worldbank.org/v2/country/SGP/indicator/NE.EXP.GNFS.ZS?format=json
# 新加坡进口（占GDP）
https://api.worldbank.org/v2/country/SGP/indicator/NE.IMP.GNFS.ZS?format=json
```

