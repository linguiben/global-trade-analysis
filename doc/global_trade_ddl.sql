-- ============ SCHEMA SETUP ============
CREATE SCHEMA IF NOT EXISTS public;
SET search_path TO public;

-- ============ DIMENSION TABLES ============

--select  dim_country;
-- 维表：国家（包含所有交易伙伴 + GDP 国家）
CREATE TABLE IF NOT EXISTS dim_country  (
    country_id    BIGSERIAL PRIMARY KEY,
    name_en       VARCHAR(128) ,
    name_cn       VARCHAR(128),
    iso_alpha2    CHAR(2),
    iso_alpha3    CHAR(3),
    region        VARCHAR(64),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- select * from dim_country

-- 维表：数据来源
CREATE TABLE IF NOT EXISTS dim_source (
    source_id     BIGSERIAL PRIMARY KEY,
    source_key    VARCHAR(128) NOT NULL UNIQUE,
    display_name  VARCHAR(256) ,
    agency        VARCHAR(256),
    url           TEXT,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- select * from dim_period

-- 维表：时期
CREATE TABLE IF NOT EXISTS dim_period (
    period_id     BIGSERIAL PRIMARY KEY,
    period_start  DATE ,
    period_end    DATE ,
    granularity   VARCHAR(16) NOT NULL CHECK (granularity IN ('month','ytd','annual','quarter')),
    label         VARCHAR(64),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (period_start, period_end, granularity)
);

-- ============ FACT TABLES ============
-- 事实表：GDP 数据
CREATE TABLE IF NOT EXISTS fact_gdp (
    country_id              BIGINT NOT NULL REFERENCES dim_country(country_id) ON DELETE RESTRICT,
    source_id               BIGINT NOT NULL REFERENCES dim_source(source_id) ON DELETE RESTRICT,
    period_id               BIGINT NOT NULL REFERENCES dim_period(period_id) ON DELETE RESTRICT,
    ranking                 INTEGER,
    currency                VARCHAR(16) NOT NULL DEFAULT 'USD',
    unit                    VARCHAR(32) NOT NULL DEFAULT 'trillion',
    gdp_nominal             NUMERIC(14,4),
    gdp_growth_rate_pct     NUMERIC(7,4),
    remarks                 TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

/* query: GDP
select * from fact_gdp;
select c.*,f.*
from fact_gdp f 
inner join dim_country c on f.country_id = c.country_id
*/

-- 事实表：双边贸易数据
CREATE TABLE IF NOT EXISTS fact_trade (
    source_id               BIGINT NOT NULL REFERENCES dim_source(source_id) ON DELETE RESTRICT,
    period_id               BIGINT NOT NULL REFERENCES dim_period(period_id) ON DELETE RESTRICT,
    export_country_id       BIGINT NOT NULL REFERENCES dim_country(country_id) ON DELETE RESTRICT,
    import_country_id       BIGINT NOT NULL REFERENCES dim_country(country_id) ON DELETE RESTRICT,
    currency                VARCHAR(16) ,
    unit                    VARCHAR(32) ,
    remarks                 TEXT,
    amount           		NUMERIC(18,4) ,
    yoy_pct         		 NUMERIC(7,4),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
/*
select * from fact_trade
 */


-- ============ INDEXES ============
CREATE INDEX idx_fact_trade_country ON fact_trade(country_id);
CREATE INDEX idx_fact_trade_source ON fact_trade(source_id);
CREATE INDEX idx_fact_trade_period ON fact_trade(period_id);
CREATE INDEX idx_fact_gdp_country ON fact_gdp(country_id);
CREATE INDEX idx_fact_gdp_source ON fact_gdp(source_id);
CREATE INDEX idx_fact_gdp_period ON fact_gdp(period_id);

-- ============ COMMENTS ============
COMMENT ON TABLE dim_country IS '国家维表：包含所有国家和地区';
COMMENT ON TABLE dim_source IS '数据来源表（Eurostat / US Census / IMF 等）';
COMMENT ON TABLE dim_period IS '时期维表，支持月度、年度、YTD 等粒度';
COMMENT ON TABLE fact_trade IS '双边贸易事实表：存储出口、进口、贸易余额等度量';
COMMENT ON TABLE fact_gdp IS 'GDP 事实表：存储国家 GDP 名义值和增长率';
COMMENT ON COLUMN fact_gdp.gdp_nominal IS '名义 GDP（单位由 unit 字段指定，默认万亿美元）';



-- ============ INSERT DATA ============

-- 1. 插入来源
INSERT INTO dim_source (source_key, display_name, agency, url, notes) VALUES
('us_census_bureau', 'US Census Bureau - Goods trade statistics', 'US Census Bureau', 'https://www.census.gov', '美国商务部普查局，货物贸易统计，截至2025年11月年内累计'),
('eurostat', 'Eurostat - External trade', 'Eurostat', 'https://ec.europa.eu/eurostat', '欧洲统计局，2025年11月单月非季节调整数据'),
('imf', 'IMF World Economic Outlook', 'International Monetary Fund', 'https://www.imf.org/en/publications/WEO', '国际货币基金组织，2025年全球经济展望');
INSERT INTO dim_country (name_en, name_cn, iso_alpha2, iso_alpha3, region) VALUES
('ASEAN', '东盟', NULL, NULL, 'Asia'),
('EU', '欧盟', NULL, NULL, 'Europe'),
('Hong Kong, China', '香港（中国）', 'HK', 'HKG', 'Asia'),
('Belt and Road Initiative partners', '“一带一路”共建国家', NULL, NULL, 'Various');
-- 1) 添加 China Customs 数据源（若已存在则不重复）
INSERT INTO dim_source (source_key, display_name, agency, url, notes)
VALUES ('china_customs', 'China Customs - GACC 货物贸易统计', 'General Administration of Customs of PRC', 'http://english.customs.gov.cn', '中国海关总署，2025年1-11月累计')
ON CONFLICT (source_key) DO NOTHING;

-- 2. 插入时期
INSERT INTO dim_period (period_start, period_end, granularity, label) VALUES
('2025-01-01', '2025-11-30', 'ytd', '2025 YTD to Nov'),
('2025-11-01', '2025-11-30', 'month', '2025-11'),
('2025-01-01', '2025-12-31', 'annual', '2025');

-- 3. 插入国家（26个，涵盖贸易与GDP数据中的所有国家）
INSERT INTO dim_country (name_en, name_cn, iso_alpha2, iso_alpha3, region) VALUES
('Mexico', '墨西哥', 'MX', 'MEX', 'Americas'),
('Canada', '加拿大', 'CA', 'CAN', 'Americas'),
('China', '中国', 'CN', 'CHN', 'Asia'),
('Taiwan', '中国台湾', 'TW', 'TWN', 'Asia'),
('Vietnam', '越南', 'VN', 'VNM', 'Asia'),
('Germany', '德国', 'DE', 'DEU', 'Europe'),
('Japan', '日本', 'JP', 'JPN', 'Asia'),
('South Korea', '韩国', 'KR', 'KOR', 'Asia'),
('United Kingdom', '英国', 'GB', 'GBR', 'Europe'),
('India', '印度', 'IN', 'IND', 'Asia'),
('United States', '美国', 'US', 'USA', 'Americas'),
('Switzerland', '瑞士', 'CH', 'CHE', 'Europe'),
('Türkiye', '土耳其', 'TR', 'TUR', 'Europe'),
('Norway', '挪威', 'NO', 'NOR', 'Europe'),
('France', '法国', 'FR', 'FRA', 'Europe'),
('Italy', '意大利', 'IT', 'ITA', 'Europe'),
('Russia', '俄罗斯', 'RU', 'RUS', 'Europe'),
('Brazil', '巴西', 'BR', 'BRA', 'Americas'),
('Spain', '西班牙', 'ES', 'ESP', 'Europe'),
('Australia', '澳大利亚', 'AU', 'AUS', 'Oceania'),
('Indonesia', '印度尼西亚', 'ID', 'IDN', 'Asia'),
('Ireland', '爱尔兰', 'IE', 'IRL', 'Europe'),
('Philippines', '菲律宾', 'PH', 'PHL', 'Asia'),
('South Sudan', '南苏丹', 'SS', 'SSD', 'Africa'),
('Libya', '利比亚', 'LY', 'LBY', 'Africa'),
('Guyana', '圭亚那', 'GY', 'GUY', 'Americas'),
('Ethiopia', '埃塞俄比亚', 'ET', 'ETH', 'Africa');
-- 新加坡
INSERT INTO public.dim_country (name_en, name_cn, iso_alpha2, iso_alpha3, region)
SELECT 'Singapore', '新加坡', 'SG', 'SGP', 'Asia'
WHERE NOT EXISTS (
SELECT 1 FROM public.dim_country
WHERE name_en = 'Singapore' OR iso_alpha2 = 'SG' OR iso_alpha3 = 'SGP'
);

-- 马来西亚
INSERT INTO public.dim_country (name_en, name_cn, iso_alpha2, iso_alpha3, region)
SELECT 'Malaysia', '马来西亚', 'MY', 'MYS', 'Asia'
WHERE NOT EXISTS (
SELECT 1 FROM public.dim_country
WHERE name_en = 'Malaysia' OR iso_alpha2 = 'MY' OR iso_alpha3 = 'MYS'
);

-- 泰国
INSERT INTO public.dim_country (name_en, name_cn, iso_alpha2, iso_alpha3, region)
SELECT 'Thailand', '泰国', 'TH', 'THA', 'Asia'
WHERE NOT EXISTS (
SELECT 1 FROM public.dim_country
WHERE name_en = 'Thailand' OR iso_alpha2 = 'TH' OR iso_alpha3 = 'THA'
);
-- 6. 插入 IMF GDP 数据（2025 annual，单位：万亿美元）
INSERT INTO fact_gdp
(country_id, source_id, period_id, ranking, currency, unit, gdp_nominal, gdp_growth_rate_pct) VALUES
((SELECT country_id FROM dim_country WHERE name_en='United States'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 1, 'USD', 'trillion', 30.62, 2.00),

((SELECT country_id FROM dim_country WHERE name_en='China'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 2, 'USD', 'trillion', 19.4, 4.80),

((SELECT country_id FROM dim_country WHERE name_en='Germany'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 3, 'USD', 'trillion', 5.01, 0.20),

((SELECT country_id FROM dim_country WHERE name_en='Japan'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 4, 'USD', 'trillion', 4.28, 1.10),

((SELECT country_id FROM dim_country WHERE name_en='India'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 5, 'USD', 'trillion', 4.13, 6.60),

((SELECT country_id FROM dim_country WHERE name_en='United Kingdom'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 6, 'USD', 'trillion', 3.96, 1.30),

((SELECT country_id FROM dim_country WHERE name_en='France'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 7, 'USD', 'trillion', 3.36, 0.70),

((SELECT country_id FROM dim_country WHERE name_en='Italy'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 8, 'USD', 'trillion', 2.54, 0.50),

((SELECT country_id FROM dim_country WHERE name_en='Russia'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 9, 'USD', 'trillion', 2.54, 0.60),

((SELECT country_id FROM dim_country WHERE name_en='Canada'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 10, 'USD', 'trillion', 2.28, 1.20),

((SELECT country_id FROM dim_country WHERE name_en='Brazil'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 11, 'USD', 'trillion', 2.26, 2.40),

((SELECT country_id FROM dim_country WHERE name_en='Spain'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 12, 'USD', 'trillion', 1.89, 2.90),

((SELECT country_id FROM dim_country WHERE name_en='Mexico'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 13, 'USD', 'trillion', 1.86, 1.00),

((SELECT country_id FROM dim_country WHERE name_en='South Korea'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 14, 'USD', 'trillion', 1.86, 0.90),

((SELECT country_id FROM dim_country WHERE name_en='Australia'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 15, 'USD', 'trillion', 1.83, 1.80),

((SELECT country_id FROM dim_country WHERE name_en='Indonesia'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 17, 'USD', 'trillion', 1.44, 4.90),

((SELECT country_id FROM dim_country WHERE name_en='Taiwan'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 22, 'USD', 'trillion', 0.88, 3.70),

((SELECT country_id FROM dim_country WHERE name_en='Ireland'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 24, 'USD', 'trillion', 0.71, 9.10),

((SELECT country_id FROM dim_country WHERE name_en='Philippines'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 33, 'USD', 'trillion', 0.49, 5.40),

((SELECT country_id FROM dim_country WHERE name_en='Vietnam'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 34, 'USD', 'trillion', 0.48, 6.50),

((SELECT country_id FROM dim_country WHERE name_en='South Sudan'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 NULL, 'USD', 'trillion', NULL, 24.30),

((SELECT country_id FROM dim_country WHERE name_en='Libya'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 NULL, 'USD', 'trillion', NULL, 15.60),

((SELECT country_id FROM dim_country WHERE name_en='Guyana'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 NULL, 'USD', 'trillion', NULL, 10.30),

((SELECT country_id FROM dim_country WHERE name_en='Ethiopia'),
 (SELECT source_id FROM dim_source WHERE source_key='imf'),
 (SELECT period_id FROM dim_period WHERE label='2025'),
 NULL, 'USD', 'trillion', NULL, 7.20);

-- 4. 插入 双边贸易数据 事实表
-- 2) 使用 China Customs：2025 年 1-11 月中国主要贸易伙伴（单位：百万美元）
-- 为每个伙伴插入三条记录：total / export / import，remarks 标注类型


INSERT INTO fact_trade (source_id, period_id, export_country_id, import_country_id, currency, unit, remarks, amount, yoy_pct)
VALUES
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='ASEAN'),
'USD','million','total 进出口 (China ↔ ASEAN) 2025 Jan-Nov', 952844.1, 7.7
)
,
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='ASEAN'),
'USD','million','export (China → ASEAN) 2025 Jan-Nov', 599033.5, 7.7
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='ASEAN'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','import (ASEAN → China) 2025 Jan-Nov', 353810.6, 7.7
),

(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
'USD','million','total 进出口 (China ↔ EU) 2025 Jan-Nov', 749342.7, 4.6
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
'USD','million','export (China → EU) 2025 Jan-Nov', 508047.9, 4.6
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','import (EU → China) 2025 Jan-Nov', 241294.8, 4.6
),

(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
'USD','million','total 进出口 (China ↔ US) 2025 Jan-Nov', 514662.1, -17.5
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
'USD','million','export (China → US) 2025 Jan-Nov', 300461.8, -17.5
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','import (US → China) 2025 Jan-Nov', 128755.1, -17.5
),

(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Hong Kong, China'),
'USD','million','total 进出口 (China ↔ Hong Kong) 2025 Jan-Nov', 328687.1, 17.2
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Hong Kong, China'),
'USD','million','export (China → Hong Kong) 2025 Jan-Nov', 300461.8, 17.2
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='Hong Kong, China'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','import (Hong Kong → China) 2025 Jan-Nov', 28225.3, 17.2
),

(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='South Korea'),
'USD','million','total 进出口 (China ↔ South Korea) 2025 Jan-Nov', 298895.4, 0.8
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='South Korea'),
'USD','million','export (China → South Korea) 2025 Jan-Nov', 130696.9, 0.8
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='South Korea'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','import (South Korea → China) 2025 Jan-Nov', 168198.4, 0.8
),

(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Japan'),
'USD','million','total 进出口 (China ↔ Japan) 2025 Jan-Nov', 292605.1, 4.6
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Japan'),
'USD','million','export (China → Japan) 2025 Jan-Nov', 144176.3, 4.6
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='Japan'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','import (Japan → China) 2025 Jan-Nov', 148428.8, 4.6
),

(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Taiwan'),
'USD','million','total 进出口 (China ↔ Taiwan) 2025 Jan-Nov', 285395.1, 7.3
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Taiwan'),
'USD','million','export (China → Taiwan) 2025 Jan-Nov', 76004.8, 7.3
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='Taiwan'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','import (Taiwan → China) 2025 Jan-Nov', 209390.3, 7.3
),

(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Russia'),
'USD','million','total 进出口 (China ↔ Russia) 2025 Jan-Nov', 203675.1, -8.7
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Russia'),
'USD','million','export (China → Russia) 2025 Jan-Nov', 91606.8, -8.7
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='Russia'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','import (Russia → China) 2025 Jan-Nov', 112068.3, -8.7
),

(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Brazil'),
'USD','million','total 进出口 (China ↔ Brazil) 2025 Jan-Nov', 170809.9, -2.2
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Brazil'),
'USD','million','export (China → Brazil) 2025 Jan-Nov', 65415.0, -2.2
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='Brazil'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','import (Brazil → China) 2025 Jan-Nov', 105394.9, -2.2
),

(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Belt and Road Initiative partners'),
'USD','million','total 进出口 (China ↔ Belt and Road partners) 2025 Jan-Nov', 2978139.6, 5.3
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='Belt and Road Initiative partners'),
'USD','million','export (China → Belt and Road partners) 2025 Jan-Nov', 1723572.4, 5.3
),
(
(SELECT source_id FROM dim_source WHERE source_key='china_customs'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='Belt and Road Initiative partners'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','import (Belt and Road partners → China) 2025 Jan-Nov', 1254567.2, 5.3
);

-- 3) 使用 US Census：2025 年截至 11 月美国与主要伙伴货物贸易（原表单位：十亿美元 → 转为百万美元，乘以1000）
-- 仅插入与仓库中国家匹配的行（Mexico, Canada, China, Taiwan, Vietnam, Germany, Japan, South Korea, United Kingdom, India）
INSERT INTO fact_trade (source_id, period_id, export_country_id, import_country_id, currency, unit, remarks, amount, yoy_pct)
VALUES
(
(SELECT source_id FROM dim_source WHERE source_key='us_census_bureau'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='Mexico'),
'USD','million','total (US ↔ Mexico) 2025 Jan-Nov (US Census)', 802300.0, NULL
),
(
(SELECT source_id FROM dim_source WHERE source_key='us_census_bureau'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='Canada'),
'USD','million','total (US ↔ Canada) 2025 Jan-Nov (US Census)', 661200.0, NULL
),
(
(SELECT source_id FROM dim_source WHERE source_key='us_census_bureau'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'USD','million','total (US ↔ China) 2025 Jan-Nov (US Census)', 385200.0, NULL
),
(
(SELECT source_id FROM dim_source WHERE source_key='us_census_bureau'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='Taiwan'),
'USD','million','total (US ↔ Taiwan) 2025 Jan-Nov (US Census)', 226600.0, NULL
),
(
(SELECT source_id FROM dim_source WHERE source_key='us_census_bureau'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='Vietnam'),
'USD','million','total (US ↔ Vietnam) 2025 Jan-Nov (US Census)', 190800.0, NULL
),
(
(SELECT source_id FROM dim_source WHERE source_key='us_census_bureau'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='Germany'),
'USD','million','total (US ↔ Germany) 2025 Jan-Nov (US Census)', 216700.0, NULL
),
(
(SELECT source_id FROM dim_source WHERE source_key='us_census_bureau'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='Japan'),
'USD','million','total (US ↔ Japan) 2025 Jan-Nov (US Census)', 209500.0, NULL
),
(
(SELECT source_id FROM dim_source WHERE source_key='us_census_bureau'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='South Korea'),
'USD','million','total (US ↔ South Korea) 2025 Jan-Nov (US Census)', 176300.0, NULL
),
(
(SELECT source_id FROM dim_source WHERE source_key='us_census_bureau'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='United Kingdom'),
'USD','million','total (US ↔ United Kingdom) 2025 Jan-Nov (US Census)', 147300.0, NULL
),
(
(SELECT source_id FROM dim_source WHERE source_key='us_census_bureau'),
(SELECT period_id FROM dim_period WHERE label='2025 YTD to Nov'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='India'),
'USD','million','total (US ↔ India) 2025 Jan-Nov (US Census)', 137500.0, NULL
);

-- 4) 使用 Eurostat：2025 年 11 月 EU 对主要伙伴单月（原单位：亿欧元 → 转为百万欧元：乘以100）
-- 插入 export（EU → partner）和 import（partner → EU）两条记录，period 使用 '2025-11'
INSERT INTO fact_trade (source_id, period_id, export_country_id, import_country_id, currency, unit, remarks, amount, yoy_pct)
VALUES
(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
'EUR','million','EU export Nov 2025 → United States (Eurostat)', 37400.0, -20.3
),
(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='United States'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
'EUR','million','EU import Nov 2025 ← United States (Eurostat)', 26700.0, -7.1
),

(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
'EUR','million','EU export Nov 2025 → China (Eurostat)', 16400.0, -1.2
),
(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='China'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
'EUR','million','EU import Nov 2025 ← China (Eurostat)', 48700.0, 3.8
),

(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
(SELECT country_id FROM dim_country WHERE name_en='United Kingdom'),
'EUR','million','EU export Nov 2025 → United Kingdom (Eurostat)', 28400.0, -6.0
),
(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='United Kingdom'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
'EUR','million','EU import Nov 2025 ← United Kingdom (Eurostat)', 13000.0, -4.7
),

(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
(SELECT country_id FROM dim_country WHERE name_en='Switzerland'),
'EUR','million','EU export Nov 2025 → Switzerland (Eurostat)', 18700.0, 6.7
),
(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='Switzerland'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
'EUR','million','EU import Nov 2025 ← Switzerland (Eurostat)', 12300.0, -1.9
),

(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
(SELECT country_id FROM dim_country WHERE name_en='Japan'),
'EUR','million','EU export Nov 2025 → Japan (Eurostat)', 5300.0, -19.4
),
(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='Japan'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
'EUR','million','EU import Nov 2025 ← Japan (Eurostat)', 5100.0, -5.0
),

(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
(SELECT country_id FROM dim_country WHERE name_en='Türkiye'),
'EUR','million','EU export Nov 2025 → Türkiye (Eurostat)', 9600.0, -3.6
),
(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='Türkiye'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
'EUR','million','EU import Nov 2025 ← Türkiye (Eurostat)', 8100.0, 1.1
),

(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
(SELECT country_id FROM dim_country WHERE name_en='Norway'),
'EUR','million','EU export Nov 2025 → Norway (Eurostat)', 5900.0, 9.2
),
(
(SELECT source_id FROM dim_source WHERE source_key='eurostat'),
(SELECT period_id FROM dim_period WHERE label='2025-11'),
(SELECT country_id FROM dim_country WHERE name_en='Norway'),
(SELECT country_id FROM dim_country WHERE name_en='EU'),
'EUR','million','EU import Nov 2025 ← Norway (Eurostat)', 7600.0, -3.4
);