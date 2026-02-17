## Observations 与 Recommendations 的完整处理链路

dashboard_v3.html 中每个 tab 面板下都有两个独立的信息区域：**Commentary**（含 Observations/Recommendations）和 **Insight**。它们的数据来源和生成方式完全不同。

---

### 1. Observations / Recommendations — 前端实时计算，硬编码规则

**来源：纯前端 JavaScript，不经过后端 API 也不读数据库。**

它们由 dashboard_v3.html 的 `_setObsRec(containerId, obs, rec)` 函数写入页面：

```js
function _setObsRec(containerId, obs, rec) {
    el.innerHTML = `
      <div>Observations: ${obs || '—'}</div>
      <div>Recommendations: ${rec || '—'}</div>`;
}
```

**文本内容完全是在前端 JS 中用 if/else 条件判断拼接的模板字符串**，基于 `DASHBOARD_DATA`（服务端渲染时注入的快照数据）做简单数学运算后生成。每个 tab 的逻辑分散在以下位置：

| 卡片 | Tab | 生成位置 | 判断逻辑 |
|------|-----|---------|---------|
| Trade | Corridors | dashboard_v3.html | 判断 `vRows`/`volRows` 是否有数据 |
| Trade | Export/Import | dashboard_v3.html | 计算 YoY % 并用模板拼接 |
| Trade | Balance | dashboard_v3.html | 判断 `bal` 正负 → net exporter/importer |
| Trade | WCI | dashboard_v3.html | 判断 WCI 是否有值 |
| Trade | PortWatch | dashboard_v3.html | 直接使用 `pw.commentary` |
| Wealth | GDP pc | dashboard_v3.html | 固定模板文字 |
| Wealth | Consumption | dashboard_v3.html | 计算消费 YoY% |
| Wealth | Disposable pc/hh | dashboard_v3.html | 显示最新值 |
| Wealth | Age Structure | dashboard_v3.html | 取 15-64 岁占比 |
| Finance | Industry | dashboard_v3.html | 取 top industry by value |
| Finance | Country | dashboard_v3.html | 取 top country by value |

**总结：Observations/Recommendations 是规则驱动的、硬编码在前端模板中的定性描述，不涉及 LLM。**

---

### 2. Insight — 后端 LLM 生成，存数据库

每个 tab 面板下方还有一个 `Insight` 区块（圆角深色卡片），其数据来自后端数据库 `widget_insights` 表。

**完整链路：**

```
┌─────────────────────────────────────────────────────────────┐
│  定时任务 generate_homepage_insights (cron)                   │
│  → _run_generate_homepage_insights()                        │
│    → 读取各 widget_snapshot 的最新快照                         │
│    → 构建 prompt (card_key, tab_key, scope, 数据摘要)          │
│    → 调用 _gen_insight()                                     │
│      → generate_insight_with_llm() (OpenAI/Gemini API)      │
│      → 解析返回 JSON: {insight, references[]}                 │
│      → _save_insight() → INSERT INTO widget_insights         │
│      → _save_insight_generate_log() → 保存调用日志              │
└─────────────────────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────────────────────┐
│  页面渲染 (GET /v3)                                          │
│  → routes.py: _dashboard_payload() 组装 dashboard_data       │
│  → _latest_insights_map(db) 查询 widget_insights             │
│    → WHERE generated_by='llm'                               │
│    → ORDER BY card_key, tab_key, scope, id DESC              │
│    → 每组只取最新一条                                          │
│  → 注入模板: { insights: { card → tab → scope → {content} }} │
└─────────────────────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────────────────────┐
│  前端 JS 读取并显示                                           │
│  → _getInsight(card, tab, scope) 从 DASHBOARD_DATA.insights  │
│  → 写入 #xxx_insight_text 的 textContent                     │
└─────────────────────────────────────────────────────────────┘
```

---

### 3. 两者的关系总结

| 特征 | Observations / Recommendations | Insight |
|-----|-------------------------------|---------|
| 生成位置 | **前端 JS** (dashboard_v3.html) | **后端 Job** (runtime.py → insights_llm.py) |
| 数据来源 | `DASHBOARD_DATA` 中的快照数据 | `widget_insights` 数据库表 |
| 生成方式 | 硬编码模板 + if/else 条件 | LLM API 调用 (GPT/Gemini) |
| 更新频率 | 每次页面加载时实时计算 | 定时任务 (`0 7 * * *` 每天一次) |
| 是否持久化 | 否 | 是 (写入 DB) |
| 渲染容器 | `*_commentary` div | `*_insight_text` div |