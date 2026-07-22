<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# [https://github.com/raymodny-ai/PIT-Market-Intelligence-Platform](https://github.com/raymodny-ai/PIT-Market-Intelligence-Platform)  附件是项目的相关文档，项目整体数据获取和清洗的逻辑和准确性如何？项目前端一塌糊涂，帮我根据后端和项目相关文档生成一份完整和现代化交互的前端开发prd。

基于对四份文档和 GitHub 仓库前端实际代码结构的全面阅读，以下是完整评估和前端 PRD。

***

# 一、数据获取与清洗逻辑/准确性评估

整体架构设计思路严谨（双时间轴 Silver、Append-only、PIT 因果约束），但在具体数据源实现层面有若干高风险问题已被识别并进行了改进。

## 设计优点

- **FRED/ALFRED 双时间处理**逻辑正确，PRD 明确要求同时保存 `observation_time`、`release_time`、`available_at` 三个字段，并强制通过 ALFRED API 传入 `realtime_start=ingest_date` 防止使用修订值[^1]
- **CFTC COT 周五发布规则**（`cftc_friday_release`）正确反映了 CFTC 每周五 15:30 ET 发布上周二持仓的实际规律，PIT 逻辑有效防止提前使用[^2]
- **Silver append-only 模型**在 TODO v0.3 中已强制要求每条记录带 `fill_type: OBSERVED | FORWARD_FILLED | INTERPOLATED`，解决了历史上的静默替换风险 [^3]


## 已识别并修正的关键问题

| 问题 | 数据源 | 风险等级 | 修正状态 |
| :-- | :-- | :-- | :-- |
| `finra_regsho_same_day` 实为 T+1 发布，引入 1 个交易日前视偏差 | FINRA Reg SHO | 🔴 高 | ✅ T-07 已改为 `t_plus_1_afternoon` |
| yfinance `available_at` 未区分盘中/收盘/复权三态 | yfinance | 🔴 高 | ✅ T-05a 已拆分 `decision_clock: 1605_ET/1805_ET` + `price_type` 三态 |
| SEC 13F 使用 `period_of_report` 而非 `acceptancedatetime`，相差可达45天 | SEC EDGAR | 🔴 高 | ✅ T-26 已明确强制用 `acceptancedatetime` |
| GLD/IAU 跨发行方 `shares_outstanding` 可用时间误用（相差约18小时） | ETF 申赎 | 🟠 中 | ✅ T-12 case 14 已覆盖，发行方独立 availability rule |
| COT Disaggregated vs Legacy vs TFF 字段映射混用 | CFTC | 🟠 中 | ✅ Instrument Registry 新增 `cot_report_type` |
| Silver 层前向填充行与真实观测行外观相同，无法追溯 | 共性 | 🟠 中 | ✅ `fill_type` + `fill_source_observation_id` 已加入 Silver schema |
| FINRA short_ratio 分子分母不同源（局部 venue vs 全市场） | FINRA | 🟡 低-中 | ✅ 语义警告自 Source → Evidence → LLM 全链路传播 |
| CFTC `available_at` 仅存日期而不含时刻（周五 14:55 ET 时误判可得） | CFTC | 🟠 中 | ✅ 强制 `TIMESTAMPTZ` 精确到分钟 |

**整体结论**：数据获取/清洗的核心 PIT 逻辑在 v0.3 TODO 迭代后已从概念层落实到 Adapter 验收条件，风险基本可控。最大的残余风险是语义警告的全链路传播（Source→Silver→Feature→Evidence→LLM Finding）目前依赖纪律约束而非代码硬性保障，需要 Verifier 闸门强覆盖 。[^3]

***

# 二、前端开发 PRD

## PRD · PIT 研究工作台前端

**版本：** v1.0 | **状态：** 产品需求文档 | **技术栈：** Next.js 14 App Router + TypeScript + Plotly.js + AG Grid + Zustand + TanStack Query

***

## 现状诊断

当前仓库 [`raymodny-ai/PIT-Market-Intelligence-Platform`](https://github.com/raymodny-ai/PIT-Market-Intelligence-Platform) 的 `frontend/` 目录仅存在目录骨架（`app/`、`components/`、`lib/`、`stores/`、`types/`）和配置文件，无任何实质性 UI 实现。主要缺失：无交叉过滤状态管理、无 PIT 上下文感知组件、无图表与表格联动、无 SSE 流式渲染、无证据血缘抽屉 。

***

## 设计原则

1. **前端只消费冻结 PIT 资产**：所有数值、Z-score、分位数均由后端 PIT 查询返回，前端不得重算特征或自行前向填充[^4]
2. **每个数值都有溯源入口**：图表数据点、表格单元格 hover 时必须可查 `available_at`、`observation_time`、`quality_status`、`fill_type`、来源
3. **质量状态显式不静默**：STALE、SOURCE_FAILED、INFERRED_AVAILABILITY 等状态必须在 UI 中明确渲染，不得用默认值掩盖[^4]
4. **URL 即状态**：所有切片参数（标的、时间范围、因子域、decision_time）序列化到 URL，支持分享与恢复[^3]
5. **冻结报告与研究视图分离**：Frozen Report 不可修改，动态研究视图可另存为新快照

***

## 页面路由与功能矩阵

| 路由 | 页面名称 | 核心功能 |
| :-- | :-- | :-- |
| `/dashboard` | 市场概览工作台 | KPI 卡片、风险热图、多标的时间序列、交叉过滤 Filter Rail |
| `/panels/[panelId]` | PIT Panel 研究台 | Panel 宽表切片、因子对比、时间回放、数据源健康 |
| `/reports/[reportId]` | 冻结报告页 | 不可变报告渲染、LLM Finding 列表、证据展示 |
| `/findings/[findingId]` | Finding 审计页 | 完整五级血缘、证据卡片、LLM 推理链 |
| `/lineage/[entityId]` | 数据血缘图 | Finding→Evidence→Feature→Observation→Raw 图谱 |
| `/health` | 数据源健康 | Source Health Matrix、Revision Timeline、SLA 监控 |


***

## 全局状态设计（Zustand Stores）

### `sliceStore.ts`

```typescript
interface SliceState {
  symbols: string[]           // 选中标的，如 ["GLD", "SPY"]
  decisionTime: string        // ISO 8601 timestamptz
  dateRange: [string, string] // 时间范围
  domains: DomainKey[]        // price | macro | positioning | flow
  dataSources: SourceKey[]    // yfinance | cftc | finra | fred
  qualityFilter: QualityStatus[] // VALID | STALE | INFERRED | FAILED
  frequency: Frequency        // daily | weekly | monthly
}
```


### `selectionStore.ts`

跨图联动选择状态：图表 hover/click/brush 产生的 `selectedPoints`，驱动其他图表的高亮与联动筛选。

### `reportStore.ts`

当前报告的 `panel_id`、`panel_sha256`、`panel_version`，以及 SSE 流式分析任务状态（`QUEUED | EVIDENCE_READY | LLM_RUNNING | VALIDATING | PUBLISHED`）。

***

## 核心组件规格

### PITContextBar（全局吸顶）

**作用**：任何页面顶部常驻，显示当前研究上下文。

**必含字段**：`panel_id`、`decision_time`（高亮显示）、`panel_version`、`feature_version`、`overall_quality`（颜色徽章）、`data_age`（最老数据的陈旧天数）、"另存为快照"按钮。

**交互**：点击 `decision_time` 可弹出时间回放滑动条，拖拽到历史时点即触发 Panel 重建请求。

***

### FilterRail（左侧固定面板，宽 240px）

**作用**：全局切片控制器，所有参数变化立即更新 URL 并触发图表重新拉取。

**控件清单**：

- 标的多选（带资产类别分组：Stock ETF / Commodity / Volatility）
- 时间范围日历选择器（含快捷按钮：1M / 3M / 6M / YTD / 1Y）
- 因子域 CheckboxGroup（Price \& Volume / Macro \& Rates / COT Positioning / Short Flow）
- 数据源来源 CheckboxGroup（显示各源最后更新时间与状态指示灯）
- 频率切换（日频/周频）
- 质量状态过滤（VALID / STALE / 全部，带数量统计）

***

### TimeSeriesChart（Plotly.js）

**数据契约**：从 `GET /v1/panels/{panelId}/slice` 获取，响应含 `series[]`，每个 point 含：`t`（timestamp）、`v`（值）、`available_at`、`quality_status`、`fill_type`、`source_id`。

**交互规格**：

- Hover Tooltip 显示完整元数据：值、observation_time、available_at、data_age、quality、fill_type
- STALE 点以虚线段渲染；FORWARD_FILLED 点以不同色标记
- 框选（Box Select）触发 `selectionStore` 更新，联动热图高亮对应时间段
- 右上角"查看原始 Raw"图标按钮，跳转至对应 Raw manifest

**响应式**：宽度 100%，高度 300px（小）/ 400px（中）/ 600px（大），由容器 prop 控制。

***

### RiskHeatmap（Plotly.js Heatmap）

**坐标轴**：X 轴为标的（SPY/QQQ/GLD/SLV…），Y 轴为因子域（价格动能/宏观/COT/短卖）。

**单元格值**：Z-score（后端计算，范围 -3 to +3），颜色 scheme：蓝（空头）→ 白（中性）→ 红（多头）。

**交互**：点击单元格 → FilterRail 自动设置为该标的 + 该因子域 + 联动 TimeSeriesChart 切换到对应序列；悬停显示 tooltip：`z_score`、`percentile_rank`、`quality_status`、`available_at`。

***

### AGGridPanel（AG Grid Community）

**用途**：PIT Panel 宽表展示，`/panels/[panelId]` 页面主体。

**必要列组**：

- **标识**：`canonical_symbol`、`decision_time`、`panel_version`
- **价格**：`close_raw`、`close_adj`、`z_score_63d`、`return_1d`、`return_5d`
- **宏观**：`real_rate_10y`、`dxy_z_score`、`vix_level`、`hy_spread`
- **COT**：`managed_money_net`、`cot_net_pct_oi`、`crowd_score`
- **短卖**：`short_ratio_finra`、`short_flow_z_score`

**单元格渲染**：

- 数值单元格带颜色条（绝对 Z-score 越高色越深）
- 右键单元格 → 上下文菜单："查看证据"（打开 EvidenceDrawer）/ "查看血缘"（跳转 `/lineage`）/ "导出此行"
- `quality_status` 列使用图标徽章：✅ VALID / ⚠️ STALE / ❓ INFERRED / ❌ FAILED

**服务端分页**：每页 50 行，支持服务端排序与筛选，避免大表 OOM 。[^4]

***

### EvidenceDrawer（Slide-over Panel，宽 480px）

**触发方式**：Finding 卡片点击、表格单元格右键"查看证据"、图表数据点 click。

**内容结构**：

```
Finding 标题 + 置信度徽章
─────────────────────────
结论段落（含 limitations_zh 警告块，黄色背景）
─────────────────────────
证据列表（每条 evidence_id）：
  ┌─ 字段名 / 来源 / observation_time / available_at
  ├─ 当前值 + quality_status 徽章
  ├─ Z-score / 分位数 / 语义说明
  └─ "查看完整血缘" 按钮 → 跳转 LineageDrawer
─────────────────────────
[另存为注释] [导出 JSON] [关闭]
```

**STALE/INFERRED 证据**：顶部显示橙色横幅："⚠️ 以下 N 条证据已陈旧（最大 stale_days 天），结论置信度已自动降级"，对应 `final_confidence` cap 逻辑在后端完成，前端仅展示 。[^3]

***

### LineageDrawer（五级下钻树状图）

**层级**：Finding → Evidence → Feature Observation → Silver Observation → Raw Manifest

**每节点展示**：

- Finding：`finding_id`、`analysis_run_id`、`created_at`
- Evidence：`evidence_id`、`field_name`、`value`、`quality_status`
- Feature：`feature_id`、`feature_version`、`configuration_hash`、`window_config`
- Observation：`observation_id`、`observation_time`、`available_at`、`fill_type`
- Raw：`manifest_id`、`source_url`（可点击）、`sha256`、`ingested_at`、`request.json` 预览

***

### SSEProgressBar（全局 Toast 区域）

**监听端点**：`GET /v1/analyses/{id}/stream`，支持 `Last-Event-ID` 断点续传。

**五阶段显示**：

```
[●───────] QUEUED          → 灰色
[●●──────] EVIDENCE_READY  → 蓝色，显示 evidence 数量
[●●●─────] LLM_RUNNING     → 蓝色动画，显示 model 名
[●●●●────] VALIDATING      → 橙色，显示校验规则数
[●●●●●───] PUBLISHED       → 绿色，显示 finding 数量
        → REJECTED         → 红色，显示拒绝原因
```

断线自动重连（最多 3 次，间隔指数退避），重连后从 `Last-Event-ID` 续传 。[^4]

***

### RevisionTimeline（`/health` 页面）

**作用**：宏观数据 vintage 修订对比，对应 ALFRED 的 as-of-date 机制。

**交互**：顶部切换按钮 "as-known（历史发布值）/ latest（最新修订值）"，切换后图表数值变化以红色差值层叠显示；点击修订事件点 → EvidenceDrawer 展示该 vintage 的 Raw manifest。

***

### SourceHealthMatrix（`/health` 页面）

**数据**：从 `GET /v1/sources/health` 获取。

**矩阵布局**：行 = 数据源（yfinance / CFTC / FINRA / FRED），列 = 关键字段或标的；单元格颜色：🟢 新鲜 / 🟡 轻度陈旧（≤ max_staleness/2）/ 🔴 严重陈旧或失败。

**强制规则**：至少1条陈旧数据时必须显示红色，不得静默 。[^4]

***

## API 契约（前端消费）

| 端点 | 用途 | 关键响应字段 |
| :-- | :-- | :-- |
| `GET /v1/panels/{id}/slice` | 时间序列切片 | `series[].points[].available_at`、`quality_status`、`fill_type` |
| `GET /v1/panels/{id}/heatmap` | 风险热图数据 | `cells[].z_score`、`percentile_rank`、`quality_status` |
| `GET /v1/panels/{id}/table` | AG Grid 宽表（分页） | `rows[]`、`total`、`page_info` |
| `GET /v1/findings/{id}` | Finding 详情 | `evidence_ids[]`、`limitations_zh`、`final_confidence` |
| `GET /v1/findings/{id}/lineage` | 五级血缘 | `nodes[]`（类型化）、`edges[]` |
| `GET /v1/sources/health` | 数据源健康状态 | `sources[].stale_days`、`last_ingested_at`、`status` |
| `GET /v1/analyses/{id}/stream` | SSE 分析进度 | `event`、`id`（续传用）、`data.status`、`data.progress_pct` |


***

## 前端技术规范

### 依赖版本锁定

```json
{
  "next": "14.x",
  "react": "18.x",
  "typescript": "5.x (strict)",
  "plotly.js": "2.x",
  "ag-grid-community": "31.x",
  "zustand": "4.x",
  "@tanstack/react-query": "5.x",
  "zod": "3.x",
  "tailwindcss": "3.x"
}
```


### 性能要求

- 首屏 Dashboard LCP < 2.5s（数据骨架占位符，图表懒加载）
- 切片参数变化到图表更新 < 500ms（TanStack Query 缓存命中）
- 大表（>1000行）必须走服务端分页，不在客户端全量加载


### 类型安全

- `types/api.ts` 中所有 API 响应类型用 `zod` schema 定义，运行时解析验证
- Zustand store 全部 TypeScript strict，无 `any`
- Plotly 图表配置类型用 `Partial<Plotly.Layout>` 约束


### 错误与降级

- API 失败 → ErrorBoundary 展示错误摘要，不崩溃全页
- SSE 断线 → 自动重连提示，不阻塞页面交互
- 空数据 → EmptyState 组件显示"当前切片无数据"（区分"无数据"和"质量过滤后无数据"）

***

## 交付阶段对应 TODO

| PRD 模块 | 对应 TODO | Phase |
| :-- | :-- | :-- |
| 骨架路由 + PITContextBar + FilterRail | T-02 | Phase 0 |
| TimeSeriesChart + RiskHeatmap + AGGrid 基础版 | T-11（基础看板） | Phase 1 |
| FilterRail 交叉过滤 + URL 状态序列化 + SSE 基础 | T-15/T-16/T-17 | Phase 2 |
| EvidenceDrawer + LineageDrawer + SSE 完整版 | T-24/T-23 | Phase 3 |
| RevisionTimeline + SourceHealthMatrix | T-27 | Phase 4 |

<div align="center">⁂</div>

[^1]: PRD-PIT-Market-Intelligence-Platform.mdFu-Jian-Shi-Xiang-Mu-prd-TO-3.md

[^2]: Shu-Ju-Huo-Qu-Yu-Qing-Xi-De-Luo-Ji-He-Zhun-Que-Xing-De-Gai-Jin-Yi-Jian.md

[^3]: TODO-4.md

[^4]: PRD-PIT-Market-Intelligence-Platform-2.md

