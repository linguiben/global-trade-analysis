-- DDL + INSERT for 2025年1-11月中国主要贸易伙伴进出口数据（单位：百万美元）
-- Table: public.china_trade_partners_2025_01_11

/* drop tabel if exists
drop table if exists public.tmp_china_trade_partners_2025_01_11;
drop table if exists public.tmp_eu_trade_nov_2025;
drop table if exists public.tmp_hk_trade_partners_2025;
drop table if exists public.tmp_us_trade_partners_2025_11;
*/

-- Create table
CREATE TABLE IF NOT EXISTS public.tmp_china_trade_partners_2025_01_11 (
    id SERIAL PRIMARY KEY,
    partner_cn TEXT NOT NULL,
    partner_en TEXT,
    country_id INTEGER,
    total_trade_musd NUMERIC(16,1) NOT NULL,
    export_musd NUMERIC(16,1) NOT NULL,
    import_musd NUMERIC(16,1) NOT NULL,
    yoy_pct NUMERIC(6,1),
    unit TEXT DEFAULT 'million USD',
    period TEXT DEFAULT '2025-01-01_to_2025-11-30',
    source TEXT DEFAULT 'China Customs'
);

-- Inserts
INSERT INTO public.tmp_china_trade_partners_2025_01_11 (partner_cn, partner_en, total_trade_musd, export_musd, import_musd, yoy_pct)
VALUES
    ('总计', 'Total', 5753617.5, 3414732.8, 2338884.7, 2.9),
    ('东盟', 'ASEAN', 952844.1, 599033.5, 353810.6, 7.7),
    ('欧盟', 'EU', 749342.7, 508047.9, 241294.8, 4.6),
    ('美国', 'US', 514662.1, 385907.0, 128755.1, -17.5),
    ('香港', 'Hong Kong, China', 328687.1, 300461.8, 28225.3, 17.2),
    ('韩国', 'R. O. Korea', 298895.4, 130696.9, 168198.4, 0.8),
    ('日本', 'Japan', 292605.1, 144176.3, 148428.8, 4.6),
    ('台湾', 'Taiwan, China', 285395.1, 76004.8, 209390.3, 7.3),
    ('俄罗斯', 'Russian Federation', 203675.1, 91606.8, 112068.3, -8.7),
    ('巴西', 'Brazil', 170809.9, 65415.0, 105394.9, -2.2),
    ('一带一路共建国家', 'Belt and Road countries', 2978139.6, 1723572.4, 1254567.2, 5.3);

-- 注：period 字段为文本，表示统计区间（2025年1-11月）。

-- ==================================================
-- 2025年美国主要贸易伙伴货物贸易表现（截至11月，年内累计）
-- 单位：十亿美元（billion USD）  数据来源：美国商务部普查局 (U.S. Census Bureau)
-- 表：public.us_trade_partners_2025_11
-- ==================================================

CREATE TABLE IF NOT EXISTS public.tmp_us_trade_partners_2025_11 (
    id SERIAL PRIMARY KEY,
    rank INTEGER,
    partner_cn TEXT NOT NULL,
    partner_en TEXT,
    country_id INTEGER,
    total_trade_bil_usd NUMERIC(12,1) NOT NULL,
    export_bil_usd NUMERIC(12,1) NOT NULL,
    import_bil_usd NUMERIC(12,1) NOT NULL,
    trade_balance_bil_usd NUMERIC(12,1),
    unit TEXT DEFAULT 'billion USD',
    period TEXT DEFAULT '2025-01-01_to_2025-11-30',
    source TEXT DEFAULT 'U.S. Census Bureau'
);

INSERT INTO public.tmp_us_trade_partners_2025_11 (rank, partner_cn, partner_en, total_trade_bil_usd, export_bil_usd, import_bil_usd, trade_balance_bil_usd)
VALUES
    (NULL, '全球总计', 'Global total', 5140.4, 2005.2, 3135.2, -1130.0),
    (1, '墨西哥', 'Mexico', 802.3, 309.8, 492.5, -182.7),
    (2, '加拿大', 'Canada', 661.2, 310.0, 351.2, -41.2),
    (3, '中国', 'China', 385.2, 97.9, 287.3, -189.4),
    (4, '台湾', 'Taiwan', 226.6, 49.9, 176.7, -126.9),
    (5, '越南', 'Vietnam', 190.8, 15.5, 175.3, -161.2),
    (6, '德国', 'Germany', 216.7, 75.9, 140.8, -65.0),
    (7, '日本', 'Japan', 209.5, 75.7, 133.8, -58.0),
    (8, '韩国', 'South Korea', 176.3, 62.9, 113.4, -50.5),
    (9, '英国', 'United Kingdom', 147.3, 88.1, 59.2, 28.9),
    (10, '印度', 'India', 137.5, 42.0, 95.5, -53.5);

-- 说明：表中 rank 可为空（用于总体汇总行）。

-- ==================================================
-- 2025年11月欧盟对主要伙伴贸易增长及差额（亿欧元计）
-- 单位：亿欧元（100 million EUR），数据来源：Eurostat（11月单月非季节调整）
-- 表：public.tmp_eu_trade_nov_2025
-- ==================================================

CREATE TABLE IF NOT EXISTS public.tmp_eu_trade_nov_2025 (
    id SERIAL PRIMARY KEY,
    partner_cn TEXT NOT NULL,
    partner_en TEXT,
    country_id INTEGER,
    export_nov_hundred_million_eur NUMERIC(10,1) NOT NULL,
    export_yoy_pct NUMERIC(5,1),
    import_nov_hundred_million_eur NUMERIC(10,1) NOT NULL,
    import_yoy_pct NUMERIC(5,1),
    trade_balance_hundred_million_eur NUMERIC(10,1),
    unit TEXT DEFAULT 'hundred million EUR',
    period TEXT DEFAULT '2025-11',
    source TEXT DEFAULT 'Eurostat'
);

INSERT INTO public.tmp_eu_trade_nov_2025 (partner_cn, partner_en, export_nov_hundred_million_eur, export_yoy_pct, import_nov_hundred_million_eur, import_yoy_pct, trade_balance_hundred_million_eur)
VALUES
    ('美国', 'United States', 374, -20.3, 267, -7.1, 107),
    ('中国', 'China', 164, -1.2, 487, 3.8, -323),
    ('英国', 'United Kingdom', 284, -6.0, 130, -4.7, 154),
    ('瑞士', 'Switzerland', 187, 6.7, 123, -1.9, 64),
    ('日本', 'Japan', 53, -19.4, 51, -5.0, 2),
    ('土耳其', 'Türkiye', 96, -3.6, 81, 1.1, 15),
    ('挪威', 'Norway', 59, 9.2, 76, -3.4, -17);

-- 说明：数值单位为“亿欧元”（hundred million EUR）。

-- ==================================================
-- 2025年香港主要贸易伙伴进出口数据表（百万港元）
-- 说明：出口含本地出口与经港转口；部分单项数据未披露以 NULL 表示
-- 数据来源：香港政府统计处 / 工业贸易署
-- 表：public.tmp_hk_trade_partners_2025
-- ==================================================

CREATE TABLE IF NOT EXISTS public.tmp_hk_trade_partners_2025 (
    id SERIAL PRIMARY KEY,
    rank INTEGER,
    partner_cn TEXT NOT NULL,
    partner_en TEXT,
    country_id INTEGER,
    total_trade_m_hkd NUMERIC(14,0) NOT NULL,
    import_by_partner_m_hkd NUMERIC(14,0),
    export_to_partner_m_hkd NUMERIC(14,0),
    share_pct NUMERIC(5,2),
    unit TEXT DEFAULT 'million HKD',
    period TEXT DEFAULT '2025',
    source TEXT DEFAULT 'Hong Kong Census & Statistics Department / TID'
);

INSERT INTO public.tmp_hk_trade_partners_2025 (rank, partner_cn, partner_en, total_trade_m_hkd, import_by_partner_m_hkd, export_to_partner_m_hkd, share_pct)
VALUES
    (NULL, '全球总计', 'Global total', 10927083, 5686833, 5240250, 100.00),
    (1, '中国内地', 'Mainland China', 5620279, 2491823, 3128456, 51.40),
    (2, '中国台湾', 'Taiwan, China', 870106, 668467, 201639, 8.00),
    (3, '越南', 'Vietnam', 540912, 323587, 217325, 5.00),
    (4, '美国', 'United States', 534429, 210163, 324266, 4.90),
    (5, '新加坡', 'Singapore', 506356, 435167, 71189, 4.60),
    (6, '日本', 'Japan', 335965, 244388, 91577, 3.10),
    (7, '韩国', 'South Korea', 313986, 251732, 62254, 2.90),
    (8, '马来西亚', 'Malaysia', 268095, 196215, 71880, 2.50),
    (9, '印度', 'India', 224614, NULL, NULL, 2.10),
    (10, '泰国', 'Thailand', 172258, NULL, NULL, 1.60),
    (11, '英国', 'United Kingdom', 152773, NULL, NULL, 1.40);

-- 说明：NULL 表示原始摘要中未披露的单项进/出口额。

-- ==================================================
-- Update statements to populate `country_id` from `dim_country`
-- Notes:
--  - This assumes the `dim_country` table contains columns `country_id`, `name_en` and `name_cn`.
--  - If your dim table uses different column names, adjust the join conditions accordingly.
-- ==================================================

-- 1) China partners table
UPDATE public.tmp_china_trade_partners_2025_01_11 t
SET country_id = d.country_id
FROM public.dim_country d
WHERE (
        (t.partner_en IS NOT NULL AND lower(trim(t.partner_en)) = lower(trim(d.name_en)))
    OR (t.partner_cn IS NOT NULL AND lower(trim(t.partner_cn)) = lower(trim(d.name_cn)))
);

-- 2) US partners table
UPDATE public.tmp_us_trade_partners_2025_11 t
SET country_id = d.country_id
FROM public.dim_country d
WHERE (
        (t.partner_en IS NOT NULL AND lower(trim(t.partner_en)) = lower(trim(d.name_en)))
    OR (t.partner_cn IS NOT NULL AND lower(trim(t.partner_cn)) = lower(trim(d.name_cn)))
);

-- 3) EU Nov table
UPDATE public.tmp_eu_trade_nov_2025 t
SET country_id = d.country_id
FROM public.dim_country d
WHERE (
        (t.partner_en IS NOT NULL AND lower(trim(t.partner_en)) = lower(trim(d.name_en)))
    OR (t.partner_cn IS NOT NULL AND lower(trim(t.partner_cn)) = lower(trim(d.name_cn)))
);

-- 4) HK partners table
UPDATE public.tmp_hk_trade_partners_2025 t
SET country_id = d.country_id
FROM public.dim_country d
WHERE (
        (t.partner_en IS NOT NULL AND lower(trim(t.partner_en)) = lower(trim(d.name_en)))
    OR (t.partner_cn IS NOT NULL AND lower(trim(t.partner_cn)) = lower(trim(d.name_cn)))
);

-- Optional: add foreign key constraints (uncomment if dim_country exists and referential integrity desired)
-- ALTER TABLE public.tmp_china_trade_partners_2025_01_11 ADD CONSTRAINT fk_china_country FOREIGN KEY(country_id) REFERENCES public.dim_country(country_id);
-- ALTER TABLE public.tmp_us_trade_partners_2025_11 ADD CONSTRAINT fk_us_country FOREIGN KEY(country_id) REFERENCES public.dim_country(country_id);
-- ALTER TABLE public.tmp_eu_trade_nov_2025 ADD CONSTRAINT fk_eu_country FOREIGN KEY(country_id) REFERENCES public.dim_country(country_id);
-- ALTER TABLE public.tmp_hk_trade_partners_2025 ADD CONSTRAINT fk_hk_country FOREIGN KEY(country_id) REFERENCES public.dim_country(country_id);


/**
 * 函数：将指定数量的货币转换为“million USD”
 * 参数：
 *   amount - 货币数量
 *   unit - 货币单位
 * 返回：
 *   转换后的“million USD”数量
 * for example:
 *   SELECT unit_to_musd(100, 'million usd');
 */
CREATE OR REPLACE FUNCTION public.unit_to_musd(amount NUMERIC(16,2), unit TEXT)
RETURNS NUMERIC(16,4) AS $$
DECLARE
u TEXT := lower(trim(coalesce(unit, '')));
eur_to_usd NUMERIC := 1.10; -- EUR -> USD 汇率（可根据需要调整）
hkd_to_usd NUMERIC := 0.128; -- HKD -> USD 汇率（可根据需要调整）
result NUMERIC;
BEGIN
IF amount IS NULL THEN
RETURN NULL;
END IF;

IF u IN ('million usd','million_usd') THEN
result := amount;
ELSIF u IN ('billion usd','billion_usd') THEN
result := amount * 1000; -- 1 billion USD = 1000 million USD
ELSIF u IN ('million hkd','million_hkd') THEN
-- amount 单位为“million HKD”，转换为 million USD：1 million HKD = hkd_to_usd million USD
result := amount * hkd_to_usd;
ELSIF u IN ('hundred million eur','hundred_million_eur','hundred million eur') THEN
-- amount 单位为“hundred million EUR”（即每单位=100 million EUR）
-- 转换为 million USD: amount * 100 * eur_to_usd
result := amount * 100 * eur_to_usd;
ELSE
RAISE EXCEPTION 'Unsupported unit: %', unit;
END IF;

RETURN ROUND(result::NUMERIC, 4);
END;
$$ LANGUAGE plpgsql IMMUTABLE;