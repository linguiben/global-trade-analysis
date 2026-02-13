# GTA 数据源获取与展示（Deep Research）

> 目的：依据 `doc/20260213需求分析.md`，为 GTA 各模块建立**可落地**的数据源方案（优先公开/免 key）、统一元数据契约（Source/Period/Definition/References）、并给出 Roadmap 与 Commentary 的引用来源清单。

---

## 1. 总体原则（数据获取 vs 展示）

1) **页面不直连外部数据源**：统一由 jobs 拉取 → 入库（WidgetSnapshot）→ 页面读取展示，避免公司网络/浏览器阻断与外部 API 波动。
2) **每个指标都必须“可解释”**：页面展示必须包含：Source（组织/链接）+ Period（日期范围/最新点）+ Unit/Frequency + Caveats（代理指标/缺失处理）。
3) **Ranking/Top N 只影响展示**：job 侧保存 Top20/Top50，前端按 TopN 截取（5/10/20）。
4) **Commentary 必须带引用**：没有 publication reference 的 commentary 降级为 “Data-only commentary（仅基于本数据）”。

---

## 2. 推荐数据源（按模块/Tab）

### 2.1 Global Trade Flow

#### A) Corridors（Value / Volume）与 Ranking
**现状**：MVP/占位数据。

**推荐主数据源（优先级）**
1) **IMF PortWatch（公开可下载 + 有 API 链接）**
   - 用途：可作为“港口活动/贸易量 nowcast”的近实时 proxy，并可用于 chokepoints（如苏伊士/巴拿马）监控。
   - 入口：
     - Data & Methodology：<https://portwatch.imf.org/pages/data-and-methodology>
     - Dataset example（Daily Port Activity Data and Trade Estimates）：<https://portwatch.imf.org/datasets/959214444157458aad969389b3ebe1a0_0/about>
     - Dataset example（Chokepoint Transit Calls and Trade Volume Estimates）：<https://portwatch.imf.org/datasets/42132aa4e2fc4d41bdaf9a445f688931_0/about>
   - 频率：daily（PortWatch 页面注明每天更新节奏）。
   - 备注：PortWatch 更偏“港口/航运代理指标”，与海关口径存在差异；适合做**高频监控**与 Roadmap/Commentary 引用。

2) **WTO API（官方指标 timeseries，可能需要注册/条款约束）**
   - 用途：中低频的官方贸易指标、以及 Roadmap（政策/贸易趋势）引用。
   - 入口：WTO API Developer Portal：<https://apiportal.wto.org/>
   - 频率：月度/季度/年度（视指标）。

3) **World Bank WITS API（聚合 UNCTAD/TRAINS 等，API 友好）**
   - 用途：贸易统计/关税/NTM 相关；也可作为“corridor/方向性贸易”更严谨的数据基础（但实现复杂度较高）。
   - 入口：<https://wits.worldbank.org/witsapiintro.aspx?lang=en>
   - User guide：<https://wits.worldbank.org/data/public/WITSAPI_UserGuide.pdf>

**落地建议（Corridors Ranking）**
- Phase 1：先用现有 `trade_corridors` snapshot 结构，扩展为 Top20/Top50：
  - `value_top[]`: `{origin, dest, value_usd, rank}`
  - `volume_top[]`: `{origin, dest, volume_kg, rank}`
- Phase 2：接入 PortWatch chokepoints / port calls 作为“corridor 活跃度 proxy”，并在 UI 显示其作为 proxy 的 caveats。

#### B) Export/Import/Balance（5Y）
**推荐数据源**：World Bank WDI（免 key，稳定）
- API：`https://api.worldbank.org/v2/country/{ISO3}/indicator/{INDICATOR}?format=json&date=YYYY:YYYY&per_page=200`
- 指标：
  - Export：`NE.EXP.GNFS.CD`（current US$）
  - Import：`NE.IMP.GNFS.CD`（current US$）
- 频率：annual
- Caveat：WDI 滞后（通常到上一年）。

#### C) Freight (WCI)
**推荐数据源**：Drewry World Container Index（公开网页，爬取/解析）
- 入口（示例页）：<https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry>
- 频率：weekly（页面按周更新）
- Caveat：网页结构可能变；若需更稳定，可引入替代（如付费数据或二次分发平台）但要注意 license。

#### D) PortWatch（tab）
**推荐数据源**：IMF PortWatch（同上）
- 在 snapshot 中明确：这是 nowcast / proxy，非海关最终统计。

---

### 2.2 Global Wealth Distribution

#### A) GDP per capita / Consumption（5Y）
**推荐数据源**：World Bank WDI（免 key，稳定）
- GDP pc：`NY.GDP.PCAP.CD`（current US$）
- Household final consumption exp：`NE.CON.PRVT.CD`（current US$）
- 频率：annual

#### B) Disposable（pc / hh）
**现状**：pc 部分已用 WB proxy/或 WPR + fallback；hh 仍需补。

**建议策略**
1) **pc**：优先 WB（免 key）做 proxy，避免 scrape 不稳定。
   - 若需要“更贴近 disposable”的 proxy，可比较：
     - `NY.GNP.PCAP.CD`（GNI per capita）
     - `NE.CON.PRVT.PC.KD`（consumption per capita constant）等
   - 必须在 `note/caveats` 中写明 proxy。

2) **hh（equivalised disposable income, USD, 年均汇率）**：
   - **OECD SDMX（免 key）**优先；非覆盖经济体再用本地统计局/或降级 proxy。
   - Caveat：不同国家“equivalised”口径与可得性差异大；必须写清楚口径。

#### C) Age Structure（ring chart）
**推荐数据源**：World Bank WDI（免 key，稳定）
- 指标（% of total population）：
  - 0–14：`SP.POP.0014.TO.ZS`
  - 15–64：`SP.POP.1564.TO.ZS`
  - 65+：`SP.POP.65UP.TO.ZS`
- 频率：annual
- 展示：适合 ring（构成/份额语义清晰）。

---

### 2.3 Global Financial Flow（M&A by industry / country）

**推荐数据源（当前可落地）**：IMAA 公共统计页面（现有实现）
- Caveat：网页结构变动风险；需要缓存 + 失败降级。

**增强建议（后续）**
- 若要更权威/可 API 化：可评估 OECD/World Bank/IMF 的 FDI/M&A 相关统计，但通常不是“交易榜单”形式；会改变产品语义。

---

## 3. Snapshot 元数据契约（支持 Source & Period & References）

建议统一每个 WidgetSnapshot 的 `payload` 至少包含以下字段（即使某些为空也要结构一致）：

```json
{
  "ok": true,
  "widget_key": "trade_exim_5y",
  "scope": "Global",
  "period": {
    "date": "2020:2024",
    "asof": "2026-02-13",
    "frequency": "annual"
  },
  "unit": "USD",
  "source": {
    "name": "World Bank WDI",
    "link": "https://api.worldbank.org/...",
    "license_note": "Attribution required; see provider terms"
  },
  "definitions": {
    "export": "NE.EXP.GNFS.CD (current US$)",
    "import": "NE.IMP.GNFS.CD (current US$)"
  },
  "caveats": ["Lagged official statistics; latest year may be t-1"],
  "references": [
    {"title": "WDI indicator page ...", "url": "...", "publisher": "World Bank", "date": "2026-01-28"}
  ],
  "data": {
    "series": [],
    "rows": []
  }
}
```

实现上不必一次性重构所有 payload；可以在 jobs runner 里逐步补齐：
- `source/link/frequency/date/unit/definitions/caveats/references[]`
- 前端 Source&Definition block 只依赖这些字段。

---

## 4. Roadmap（Global Trade 叙事主线）建议引用清单

Roadmap 的每条 bullet 建议绑定**一个“可点击的 publication”**，并把引用存入 `references[]`。

推荐候选 publication（示例）：
1) **WTO**：全球贸易统计/指标、贸易政策动态
   - WTO statistics landing：<https://www.wto.org/statistics>
   - WTO API portal：<https://apiportal.wto.org/>

2) **UNCTAD**：Global Trade Update / 贸易与发展统计与洞察
   - UNCTAD statistics hub：<https://unctad.org/statistics>
   - UNCTAD Data Hub：<https://unctadstat.unctad.org/EN/>

3) **IMF PortWatch（trade nowcast / chokepoints）**
   - Data & Methodology：<https://portwatch.imf.org/pages/data-and-methodology>

4) **World Bank（宏观背景指标）**
   - WDI API（指标页可作为引用）

5) **Drewry（航运成本冲击）**
   - WCI page：<https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry>

示例 Roadmap bullets（产品文案方向）：
- China：出口结构与目的地再配置（引用：WTO/UNCTAD 贸易统计或报告链接）
- Red Sea / chokepoints：航线绕行对运价与交付周期的影响（引用：PortWatch chokepoints dataset + Drewry WCI）
- US/EU trade policy：关税与合规不确定性（引用：WTO 数据/政策页面）
- EM demand cycle：进口需求回升或走弱（引用：WDI import / UNCTAD trade update）

---

## 5. Commentary（深度研究 + 引用）实施建议

### 5.1 来源获取（可落地、低耦合）
- **Phase 1（手工 curated）**：每个 tab 维护 1–3 条固定引用（WTO/UNCTAD/IMF/Drewry/WB），commentary 模板化。
- **Phase 2（半自动）**：
  - jobs 侧爬取 publication 页面（只抓标题/日期/摘要段落）
  - LLM 生成 commentary（必须把 references[] 一并写入）
  - 人审/抽查（避免“无依据推断”）

### 5.2 存储方式
- `WidgetSnapshot.payload.references[]`：强制每次生成写入
- 额外可选：新增 `commentary_version` 与 `commentary_updated_at` 字段，便于控制更新频率（例如周更）。

### 5.3 更新频率建议
- 高频（daily/weekly）：PortWatch、WCI（适合自动）
- 低频（monthly/quarterly）：WTO/UNCTAD 报告（适合“引用固定 + 观点周更”）

---

## 6. 许可与合规（必须在 UI 明示的部分）

- **World Bank WDI**：通常允许使用但需 attribution；建议在 Source block 给出“World Bank WDI”并链接指标/API。
- **IMF PortWatch**：数据下载与 API 使用遵循其站点条款；在 Source block 显示 IMF/PortWatch 链接。
- **Drewry**：公开页面可引用，但自动抓取需注意条款与结构变动；建议保留链接，并在 caveats 标注“public page scrape”。
- **WTO API**：可能有开发者条款/注册要求；若启用，需在文档与页面标注。

---

## 7. 下一步落地清单（工程任务）

1) 为现有 jobs payload 补齐 `source/link/unit/frequency/period/definitions/caveats/references[]`（逐个 widget 迭代）。
2) Roadmap：先做静态 curated（5 条主题 + 引用），再考虑自动化抓取。
3) Commentary：先统一模板 + 最小引用集；之后再上半自动生成。
4) Ranking/Top N：job 侧存 Top20/Top50，前端仅截取显示。
