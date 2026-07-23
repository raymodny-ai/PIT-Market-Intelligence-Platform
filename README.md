# PIT Market Intelligence Platform

> **市场情报的"录像机" —— 以"决策点"为快照锚点,把那一刻所有可获得的数据原封不动锁下来,事后回放、复核、可解释。**

PIT (Point-in-Time) Market Intelligence Platform 是一套面向量化研究/资产管理的**信息检索 + 推理**系统。它从公开数据源拉取金融观测,清洗对齐到一个统一时序模型上,然后按任意历史时点切片重建 PIT 视图,最后驱动一个 LLM 分析层产出带证据链的中文投资 finding。

```
数据源 →  摄取(ingestion)   →  银层(Silver)  →  PIT 面板(Panel)  →  分析(LLM)
       cboe_cfe / cftc / cftc_cot / etf_shares / finra_otc /
       finra_regsho / fred_alfred / sec_edgar / yfinance            DeepSeek / OpenAI / Mock
```

**核心不变量**: 任何 finding 的"成立时刻"必须能在面板里指出当时的原始观测记录 —— 这是诊断 LLM 幻觉与系统漂移的唯一保险。

---

## 目录

1. [架构与设计哲学](#1-架构与设计哲学)
2. [数据获取(Ingestion)](#2-数据获取ingestion)
3. [数据清洗与对齐(Normalization)](#3-数据清洗与对齐normalization)
4. [PIT 面板构建(PitPanelBuilder)](#4-pit-面板构建pitpanelbuilder)
5. [LLM 分析层](#5-llm-分析层)
6. [API 表面](#6-api-表面)
7. [前端功能详解](#7-前端功能详解)
8. [CLI 工具](#8-cli-工具)
9. [本地部署](#9-本地部署)
10. [Docker 部署](#10-docker-部署)
11. [测试](#11-测试)

---

## 1. 架构与设计哲学

### 为什么 PIT (Point-in-Time)?

量化研究的最大隐性 bug 是 **look-ahead bias** —— 你"在 t 时点"用了"t+30 才发布"的数据,回测看着惊艳、实盘照样亏。本平台从根源上禁止这件事:每次构建面板时,只接受 `available_at ≤ decision_time` 且 `valid_from ≤ decision_time < valid_to` 的观测。这就是 PRD 里写的 SQL 等价物:

```sql
SELECT * FROM feature_observations_bitemporal
 WHERE available_at <= $decision_time
   AND valid_from  <= $decision_time
   AND (valid_to IS NULL OR valid_to > $decision_time)
```

### 模块边界 (DDD 视角)

| 层 | 包 | 职责 | 关键类型 |
|---|---|---|---|
| 摄取 | `ingestion/adapters/` | 从上游 API 拉原始 JSON / CSV / ZIP | `YFinanceAdapter`, `SecEdgarAdapter`, ... |
| 银层 | `normalization/` + `data/` | 原始 → 标准化观测 (双时间戳 bitemporal) | `SilverObservation` |
| 特征 | `features/` | 银层 → 派生指标 | `FeatureObservation` |
| 面板 | `pit/builder.py` | 给定决策点切片 → 面板 | `PitPanelBuilder`, `PanelBuildResult` |
| API | `api/` | FastAPI 路由 + 注册表查询 | `panels_api`, `analyses_api`, `lineage_api` |
| LLM | `llm/` | Provider 抽象 + JSON validator | `LLMAdapter`, `LLMProvider`, validator |
| 血缘 | `lineage/` | LLM 推理链路 audit | Source Health Matrix, Revision Timeline |
| 存储 | `storage/` | 注册表 + 文件系统面板 | `Registry`, `InProcessCache` |

### 数据流

```
                ┌──────────────────────────────────────────────┐
                │  Ingestion (8 adapters)                       │
                │   • yfinance        • fred_alfred             │
                │   • sec_edgar       • finra_otc/regsho        │
                │   • cboe_cfe        • cftc_cot                │
                │   • etf_shares                                │
                └────────────────────┬─────────────────────────┘
                                     │  Raw manifests (parquet + json)
                                     ▼
                ┌──────────────────────────────────────────────┐
                │  Normalization (Silver Layer)                 │
                │   • Resolver (canonical_symbol / metric_id)   │
                │   • Silver (bitemporal: valid_from / to,      │
                │              available_at)                     │
                └────────────────────┬─────────────────────────┘
                                     │  SilverObservation
                                     ▼
                ┌──────────────────────────────────────────────┐
                │  Feature Engineering                          │
                │   • Vol / Beta / Z-Score / Macro overlays     │
                └────────────────────┬─────────────────────────┘
                                     │  FeatureObservation
                                     ▼
                ┌──────────────────────────────────────────────┐
                │  PIT Panel Builder                            │
                │   decision_time + universe → value_panel      │
                │                            + lineage_panel    │
                │                            + manifest.json    │
                └────────────────────┬─────────────────────────┘
                                     │  PanelBuildResult (immutable)
                                     ▼
                ┌──────────────────────────────────────────────┐
                │  LLM Analysis Layer (JSON-object validator)   │
                │   • Provider: DeepSeek / OpenAI / Mock        │
                │   • Validator: schema + evidence_ids cross-ref│
                └──────────────────────────────────────────────┘
```

---

## 2. 数据获取(Ingestion)

### 适配器清单 (`src/pit_market/ingestion/adapters/`)

| 适配器 | 上游 | 数据形态 | 更新频率 | 用途 |
|---|---|---|---|---|
| `YFinanceAdapter` | Yahoo Finance unofficial API | JSON | 1-15min 延迟 | 价格/成交量/期权/基本面 |
| `SecEdgarAdapter` | `data.sec.gov/submissions` + `xbrl/companyfacts` | JSON / XBRL | 实时 | 财报/文件披露 |
| `FredAdapter` | `api.stlouisfed.org` | CSV / JSON | 日 / 周 / 月 | 利率/CPI/PPI/M2 |
| `FredAlfredAdapter` | `alfred.stlouisfed.org` | CSV | 日 / 周 / 月 | FRED 历史 vintage |
| `CboeCfeAdapter` | `markets.cboe.com` | JSON | 实时 / 日 | VIX / VX 期货曲线 |
| `CftcCftcAdapter` | `cftc.gov/deacot*.zip` | ZIP / CSV | 周五 | 持仓报告 (COT) |
| `FinraOtcAdapter` | `otc.finra.org` | CSV | 日 | OTC / Pink sheets |
| `FinraRegShoAdapter` | `regsho.finra.org` | CSV | 日 | 裸卖空名单 |
| `EtfSharesAdapter` | ETF issuer feeds | CSV | 日 | ETF creation/redemption |

### 共用适配器接口 (`adapters/base.py`)

```python
class SourceAdapter(Protocol):
    source_name: str
    async def fetch_manifest(
        self,
        *,
        as_of: datetime,    # 决策时刻
        lookback_days: int = 7,
    ) -> RawManifest:
        """返回 RawManifest: 上游原始数据 + 自身元数据 + 质量标签。"""
```

每个 adapter 自行负责:
- **速率限制** (e.g. SEC 0.12s/req, Fred 5 req/s)
- **认证** (api_key 从环境变量读)
- **重试** (tenacity + exponential backoff)
- **raw 数据落盘** (parquet 到 `data/raw/<source>/<date>/`)

### 关键设计: bitemporal timestamps

每个 Silver 观测有**两个**时间戳:
- `valid_from` / `valid_to`: 这条观测在**业务层面**的有效区间 (e.g. 财务数据对应 FY2025 Q1)
- `available_at`: 这条观测**实际上能被拉到**的最早时刻 (发布延迟)

```
───────── time ─────────►
                  ^available_at      ^valid_to
                  │                  │
                  │   observation    │
──────────────────┴──────────────────┴────
                                       ^valid_from
                                       │
```

这允许精细处理回溯修订 (e.g. SEC 8-K/A, FRED benchmark revision), 也支持"我现在只能看到截至昨天"的现实约束。

---

## 3. 数据清洗与对齐(Normalization)

### 3.1 Resolver (`normalization/resolver.py`)

每个 adapter 输出形如 `"AAPL"`、`"BRK.B"`、`"BRK-B"`、`"MRSH"` 的原始 symbol。Resolver 统一映射到 `canonical_symbol`:

```python
"BRK.B"  → "BRK.B"        # S&P 500 用 . 分隔
"BRK-B"  → "BRK.B"        # SEC alias
"AAPL"   → "AAPL"
"MRSH"   → "MMC"          # SEC alias
```

两层映射:
1. **Direct alias table** (`config/instruments/aliases.json`) — 显式 known aliases
2. **Instrument Registry** (`config/instruments/registry.json`) — 决定 ticker 是否在 universe

`Registry.load(config_dir)` 在 app 启动时一次性加载,后续查询走 O(1) 字典。

### 3.2 Silver layer (`normalization/silver.py`)

每条上游记录被转成:

```python
@dataclass
class SilverObservation:
    canonical_symbol: str
    metric_id: str             # e.g. "yfinance.price.close"
    value: float | str | None
    unit: str                  # "USD", "PCT", "INT"
    valid_from: datetime       # 业务有效起始
    valid_to:   datetime       # 业务有效结束 (None=open-ended)
    available_at: datetime     # 可拉到的最早时刻
    source_name: str
    source_ref: str            # 上游 URL / ID
    quality_status: QualityStatus  # OK / PARTIAL / FAILED
    lineage: dict              # 转换 provenance
```

`SilverBuilder.merge_many(observations)` 处理冲突:同一 `canonical_symbol + metric_id + valid_window` 出现多条时,**较晚 `available_at` 胜出**(尊重修订)。

### 3.3 Trading Calendar (`data/trading_calendar.py`)

- 美东节假日 + 早闭市规则
- 提供 `trading_day_at(t, market="US")` → 上一个交易日收盘时间
- 给定 `decision_time` 反查 **可拉到** 的最近交易日 / 报告期

这是 PIT 重建的"日历脊柱" —— 没有它,PIT 查询会跨周末/节假日出错。

---

## 4. PIT 面板构建(PitPanelBuilder)

### 入口

```python
from pit_market.pit.builder import PitPanelBuilder

builder = PitPanelBuilder(
    silver_df=combined_silver_df,
    features_df=combined_features_df,
    feature_version="features.v1.0",
    universe_version="registry.v1.0",
)
result = builder.build(
    decision_time=datetime(2025, 1, 15, 18, 5, tzinfo=UTC),
    universe=["SPY", "QQQ", "GLD", "SLV"],
    decision_clock="1805_ET",
    output_dir="./data/gold/pit_panels",
)
```

### 输入 → 输出

| 输入 | 来源 | 含义 |
|---|---|---|
| `silver_df` | `normalization/silver.py` | 全部已标准化观测 |
| `features_df` | `features/*.py` | 派生指标 (可选) |
| `decision_time` | 调用方 | PIT 锚点 |
| `universe` | 调用方 (用户选 universe) | 要纳入面板的 symbol |

### 输出 (`PanelBuildResult`)

```python
panel_id        # sha256(decision_time + universe + feature_version)
panel_sha256    # sha256(value_panel content)  ← 内容指纹
panel_version   # 注册表 epoch
value_panel     # pl.DataFrame: 多 index (canonical_symbol, metric_id) × decision_time
lineage_panel   # pl.DataFrame: 每个 cell 的来源溯源 (valid_from/to, available_at, source_ref)
quality_report.json
panel_manifest.json  # panel 元数据 + 拓扑图
```

### 写盘格式

CLI 写**扁平 manifest**:
```
data/gold/pit_panels/cli-20260115T180500Z-SPY-QQQ-GLD-SLV/
  ├─ panel_manifest.json     # 元数据 + decision_time + universe + quality
  └─ (无 parquet, 这是已知 manifest-only 模式)
```

完整 builder (T-10+) 写**目录化面板**:
```
data/gold/pit_panels/cli-20260115T180500Z-SPY-QQQ-GLD-SLV/
  ├─ panel_manifest.json
  ├─ value_panel.parquet     # 列存, 列式压缩
  └─ lineage_panel.parquet
```

API `/v1/analyses/evidence/{panel_id}` **两种格式都接受** (`_resolve_panel()` 走 `panels_api._find_panel_manifest()` 路径),evidence 缺失时返 `catalog_empty`,LLM 可走 `DATA_QUALITY_ISSUE + NO_EVIDENCE` 合法通道。

### CLI 入口

```bash
uv run pit build --universe SPY,QQQ,GLD,SLV \
                 --decision-time 2026-01-15T18:05:00Z \
                 --output-dir ./data/gold/pit_panels
```

### HTTP API 入口 (UI 触发)

```bash
POST /v1/panels/build
Content-Type: application/json

{
  "universe": ["SPY", "QQQ", "GLD", "SLV"],
  "decision_time": "2026-01-15T18:05:00Z",
  "decision_clock": "1805_ET"
}
→ 201 { panel_id, panel_sha256, row_count, quality_status, ... }
```

UI 在 `/panels/new` 提供表单。

---

## 5. LLM 分析层

### Provider 抽象 (`llm/adapter.py`)

```python
class LLMProvider(StrEnum):
    MOCK     = "mock"
    OPENAI   = "openai"
    DEEPSEEK = "deepseek"
```

| Provider | Base URL | Default Model | API Key Env |
|---|---|---|---|
| `mock` | — | — | — |
| `openai` | (default) | `gpt-4o` | `OPENAI_API_KEY` |
| `deepseek` | `https://api.deepseek.com` | `deepseek-v4-flash` | `DEEPSEEK_API_KEY` |

**注意**: DeepSeek 实际只接受 `deepseek-v4-flash` / `deepseek-v4-pro` —— `deepseek-chat` / `gpt-4o` 等命名会被 400 拒绝。`OpenAICompatProvider` 自动按 OpenAI 兼容协议 `chat.completions.create()` 走 JSON mode:

```python
response = client.chat.completions.create(
    model=model,
    messages=[{"role":"system", ...}, {"role":"user", ...}],
    response_format={"type": "json_object"},
    temperature=0.3,
)
```

### 端到端流程

```
POST /v1/analyses  { panel_id, provider, model? }
  ↓
  ┌─ Stage 1: QUEUED ──────────────┐
  │  生成 run_id, 加入异步队列      │
  └────────────────────────────────┘
  ↓
  ┌─ Stage 2: EVIDENCE_READY ──────┐
  │  _resolve_panel(panel_id)       │
  │  → Evidence catalog (catalog_id)│
  └────────────────────────────────┘
  ↓
  ┌─ Stage 3: LLM_RUNNING ─────────┐
  │  LLMAdapter.generate(finding)   │
  │  → finding JSON 草稿           │
  └────────────────────────────────┘
  ↓
  ┌─ Stage 4: VALIDATING ──────────┐
  │  Validator:                    │
  │  1. evidence_ids ⊂ catalog     │
  │  2. classification 合法        │
  │  3. data_quality_issue 留通道   │
  │  → PUBLISHED | REJECTED        │
  └────────────────────────────────┘
  ↓
  SSE stream /v1/analyses/{run_id}/stream
  → client: 实时看到 5 个 stage
```

### Validator 规则 (`llm/validator.py`)

1. **`evidence_ids ⊆ catalog`** — 每个 finding 引用的 evidence 必须真的存在 (防御幻觉)
2. **分类合法** — `classification ∈ {MACRO_REGIME, RISK_WARNING, DATA_QUALITY_ISSUE}`
3. **`DATA_QUALITY_ISSUE + NO_EVIDENCE` 合法通道** — 空目录时 LLM 可诚实说"没数据",不强制编造

### Finding schema

```typescript
{
  finding_id: string
  panel_id: string
  classification: "MACRO_REGIME" | "RISK_WARNING" | "DATA_QUALITY_ISSUE"
  support_type: "DIRECT_EVIDENCE" | "ANALOGY" | "NO_EVIDENCE"
  confidence: number  // 0..1
  llm_confidence: number
  title_zh: string
  summary_zh: string
  detailed_summary_zh: string
  evidence_ids: string[]  // 引用 catalog
  related_symbols: string[]
  as_of_decision_time: string  // ISO 8601
  model: string
  llm_duration_ms: number
}
```

---

## 6. API 表面

**Base URL**: `http://127.0.0.1:8700` (Docker) 或 `http://127.0.0.1:8700` (native dev)

完整 OpenAPI 文档: `/docs` (Swagger UI) + `/openapi.json`

### 6.1 Panels (`/v1/panels`)

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/panels` | 列出所有面板 (最新优先) |
| GET | `/panels/latest` | 最新面板 |
| GET | `/panels/{panel_id}` | 单面板详情 (含 manifest) |
| POST | `/panels/build` | **新建面板** (UI 表单也走这) |
| POST | `/panels/{panel_id}/slice` | 切片面板 (e.g. 单 symbol) |
| POST | `/panels/replay` | 历史 PIT replay |
| GET | `/metrics/registry` | 指标注册表 |
| GET | `/instruments/registry` | 标的注册表 |

### 6.2 Analyses (`/v1/analyses`)

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/analyses/evidence/{panel_id}` | 给面板构建 evidence catalog |
| POST | `/analyses` | **触发 LLM 分析** (返回 run_id) |
| GET | `/analyses/{run_id}/stream` | **SSE 流**, 实时 5 个 stage |

### 6.3 Lineage (`/v1/lineage`)

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/lineage/{entity_id}` | 实体血缘 |
| GET | `/sources/status` | 9 个 source 健康总览 |
| GET | `/sources/{source_name}/events` | 单 source 拉取历史 |
| GET | `/lineage/analysis/{analysis_run_id}/facet` | 分析链路 facet |

### 6.4 Runs (`/v1/runs`)

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/runs/{run_id}/start` | 标记 run 开始 |
| POST | `/runs/{run_id}/progress` | 上报 progress |
| GET | `/runs/{run_id}/stream` | 拉取 SSE |

### 6.5 Health / Export

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 服务健康 + 容器元数据 |
| GET | `/v1/export/{...}` | 面板 / finding 导出为 PDF / MD |

### 6.6 CORS

明示来源: `["http://127.0.0.1:8701", "http://localhost:8701", "http://127.0.0.1:3000", "http://localhost:3000"]`。**不是同源 = 同 host**, 任何跨端口请求都过 CORS。

---

## 7. 前端功能详解

**Stack**: Next.js 14 App Router · React 18 · TypeScript · TanStack Query · Zustand · AG Grid · Lightweight-charts (Plotly) · Vitest + Testing Library

**Base URL**: `http://127.0.0.1:8701` (Docker) · 内部 listen 3000 · `NEXT_PUBLIC_API_BASE=http://127.0.0.1:8700` 内联

### 7.1 路由地图

```
/                        首页 (导航面板)
/dashboard               市场概览工作台
/dashboard/replay        历史 PIT 回放
/panels                  面板列表
/panels/new              新建面板 (表单)
/panels/[panelId]        单面板详情
/findings/[findingId]    Finding 详情
/reports/[reportId]      报告详情
/lineage/[entityId]      实体血缘
/health                  服务健康
```

### 7.2 组件矩阵 (14 个, `frontend/components/`)

| 组件 | 职责 | 关键技术 |
|---|---|---|
| `PanelSwitcher` | 顶部右侧面板下拉切换器 | React Query + URL 同步 |
| `PITContextBar` | **移动端响应式**上下文栏 (decision_time / universe / quality) | `useMounted` gate + CSS media queries |
| `AGGridPanel` | 面板数值网格 (虚拟滚动) | AG Grid v32 |
| `TimeSeriesChart` | 时序图 (多 series 重叠) | Lightweight-charts 5.x |
| `RiskHeatmap` | 风险热图 (cross-asset / cross-metric) | SVG + D3-scale |
| `FindingCard` | 单 finding 卡片 (title / summary / evidence 链接) | React, Markdown |
| `EvidenceDrawer` | 抽屉: 展示 finding 引用的 evidence 原始观测 | slide-in |
| `LineageDrawer` | 抽屉: 血缘 (source → silver → feature → panel → finding) | DAG render |
| `RevisionTimeline` | 修订时间线 (每次重 build 的版本对比) | 横向滚动 |
| `SourceHealthMatrix` | 9 source 健康矩阵 (新鲜度 / 错误率 / 上次成功) | 9×N 网格 |
| `FilterRail` | 左侧 filter rail (时间窗口 / metric / classification) | debounced URL state |
| `EmptyState` | 统一空态组件 (no-data / error / loading) | 3 variants |
| `ErrorBoundary` | 全局错误边界 (P0 tri-state error 暴露) | `componentDidCatch` |
| `SSEProgressBar` | **5 stage SSE 进度条** (QUEUED → EVIDENCE_READY → LLM_RUNNING → VALIDATING → PUBLISHED) | EventSource |

### 7.3 关键页面详解

#### `/dashboard` —— **市场概览工作台**

- 顶部: `PITContextBar` (decision_time + universe chips)
- 主体: 4 区
  - KPI cards (累计 panel 数 / finding 数 / PUBLISHED 率 / source 健康率)
  - `RiskHeatmap` (cross-asset, cross-metric)
  - `TimeSeriesChart` (3-5 主标的 90 日 overlay)
  - `FindingCard` 列表 (最新 10)
- 左侧: `FilterRail` (时间窗口 / classification / universe)
- 顶部右侧: `PanelSwitcher` (一键切换不同决策时刻)

#### `/dashboard/replay` —— **历史回放**

- 给定历史 `decision_time`, 重放**同样的 PIT 查询逻辑**,重建当时面板
- 顶部说明: "此面板基于 ≤ t 时刻可获得的数据,真实回放" —— 防止 look-ahead
- 主区: `TimeSeriesChart` (高亮决策点 marker) + `FindingCard` (历史 finding)

#### `/panels` —— **面板索引**

- 表格: panel_id / decision_time / universe / quality / row_count
- 行点击 → `/panels/[panelId]`
- 顶部"新建面板"按钮 → `/panels/new`

#### `/panels/new` —— **新建面板 (表单)**

- 字段:
  - `universe` (multi-select, 候选来自 `/v1/instruments/registry`)
  - `decision_time` (datetime picker, 默认今天 18:05 ET)
  - `decision_clock` (1605_ET / 1805_ET)
- 提交流程:
  - `POST /v1/panels/build` → 201 (panel_id)
  - 跳转 `/panels/[panelId]`
- 错误态: 表单内 tri-state `postJsonWithError` (loading / error / retry)

#### `/panels/[panelId]` —— **单面板详情**

- 顶部: `PITContextBar` (高亮 universe / decision_time)
- 主区:
  - `AGGridPanel` (左侧 value_panel)
  - `RevisionTimeline` (右侧, 多次重 build 记录)
- 抽屉: `EvidenceDrawer` (cell-level 原始观测溯源)
- 底部: "运行分析" 按钮 → 触发 `/v1/analyses`

#### `/findings/[findingId]` —— **Finding 详情**

- 主体:
  - 标题 + classification 标签
  - `FindingCard` 完整版 (含 detailed_summary_zh)
  - 引用证据列表 (click → `/lineage/{entity_id}`)
- 抽屉: `LineageDrawer` (整条推理链路可视化)

#### `/lineage/[entityId]` —— **实体血缘**

- DAG 可视化:
  - Source → Silver observation → Feature → Panel cell → Finding evidence_ids
- 表格: 每个节点的 `available_at` / `valid_from-to` / `source_ref`

#### `/health` —— **服务健康**

- API + Web 当前状态
- 容器元数据 (commit SHA / build time / image tag)
- Source health matrix (9 source 实时)

### 7.4 状态管理

- **React Query** (`@tanstack/react-query`): 服务端缓存,`staleTime: 30s`
- **Zustand** (`sliceStore.ts`): 跨页面客户端状态 (selected panel, filter draft)
- **URL**: 选中面板 / filter / 时间窗口 同步到 query string (SSR-friendly)
- **`useMounted()` gate**: 所有依赖 `Date.now()` / `toLocaleString()` 的 UI 必须 gate,避免 SSR/CSR hydration mismatch

### 7.5 E2E 测试 (`scripts/e2e-screenshots.cjs`)

```bash
node frontend/scripts/e2e-screenshots.cjs
# → 输出 7 张 PNG 到 /tmp/pit-mobile/
#   dashboard-mobile.png, dashboard-desktop.png,
#   panels-list.png, new-panel-form.png,
#   new-panel-form-mobile.png, panel-detail.png,
#   e2e-{1,2}-*.png
```

用 `puppeteer-core` + 系统 chromium,`networkidle2 + selector + 500ms settle` 触发截图。

---

## 8. CLI 工具

```bash
uv run pit --help
```

| 子命令 | 用途 |
|---|---|
| `pit build` | 构建 PIT 面板 (见 §4) |
| `pit replay` | 历史时刻 replay |
| `pit report build` | 生成投资报告 (MD / PDF) |
| `pit backtest run` | 跑回测 |
| (更多) | 注册表查询 / 健康检查 / 数据导出 |

CLI 与 HTTP API **共享同一份 `build_panel_manifest()` 函数** (在 `pit/builder.py`) —— CLI 是 source of truth,API 是其 thin wrapper。

---

## 9. 本地部署 (native)

要求: Python 3.12 (uv 0.5+) · Node 24 · Debian 12 / 类似

```bash
git clone https://github.com/raymodny-ai/PIT-Market-Intelligence-Platform
cd PIT-Market-Intelligence-Platform

# Backend
uv sync --extra etl --extra llm
.venv/bin/uv pip install jsonschema nbformat   # 注: 这俩在 [etl] 之外,需手动补到 pyproject

# Frontend
cd frontend
npm install --legacy-peer-deps
cd ..

# 启动
bash scripts/dev-start.sh   # 8700 (API) + 8701 (FE)
bash scripts/dev-stop.sh    # 停服
```

环境变量 (`backend` 启动前需注入):

```bash
export PYTHONPATH=src
export PIT_CONFIG_DIR=config
export PIT_MARKET_DATA=./data
export GOLD_PANELS_DIR=./data/gold/pit_panels
export PIT_MARKET_CACHE_BACKEND=cachetools
export DEEPSEEK_API_KEY=sk-...       # 可选,无 key 时 LLM 走 mock
export PYTHONIOENCODING=utf-8
export NEXT_PUBLIC_API_BASE=http://127.0.0.1:8700
```

---

## 10. Docker 部署

两个镜像:
- `pit-market/api:dev` (~1.48 GB) —— `python:3.12-slim + uv:0.5.11`,3 stage
- `pit-market/web:dev` (~984 MB) —— `node:20-bookworm-slim`,3 stage

端口: `8700 → 8000` (API), `8701 → 3000` (Web)

```bash
# 注入 secrets
bash scripts/setup-env-docker.sh   # 拉 DEEPSEEK_API_KEY → .env.docker (chmod 600)

# 启动
sg docker -c "docker compose -f docker-compose.dev.yml up -d --build"

# 健康
curl http://127.0.0.1:8700/health   # → 200
curl http://127.0.0.1:8701/         # → 200

# 端到端 LLM
curl -X POST http://127.0.0.1:8700/v1/analyses \
  -H "Content-Type: application/json" \
  -d '{"panel_id":"cli-20260115T180500Z-SPY-QQQ-GLD-SLV","provider":"deepseek","model":"deepseek-v4-flash"}'

# 停止
sg docker -c "docker compose -f docker-compose.dev.yml down"
```

详见 `docker/README.md` (含 5 个 build bug 的修复说明 + healthcheck 设计)。

### Watchdog cron

```bash
# 每 5 min 健康检查, 不健康自动重启 + TG 报警
bash scripts/cron-watchdog-docker.sh
```

OpenClaw cron id: `7ae8f782-0ffc-4562-8631-2505d6c693f8` · 5 min cadence · enabled

---

## 11. 测试

### Backend (pytest)

```bash
PATH=/vol1/@apphome/trim.openclaw/data/home/.local/bin:$PATH \
PYTHONPATH=src \
.venv/bin/pytest tests/backend/
```

- **363 passed · 1 skipped** (live DeepSeek integration, gated by `PIT_LIVE_LLM=1` + `DEEPSEEK_API_KEY`)
- 覆盖: ingestion adapters / silver normalization / PIT builder / API contract / LLM provider / validator / manifest-only 面板 fallback

### Frontend (vitest)

```bash
cd frontend && npm run test
```

- **32 passed** (组件快照 + API client + formatting helpers)
- TypeScript: `tsc --noEmit` clean

### E2E (puppeteer-core)

```bash
node frontend/scripts/e2e-screenshots.cjs
# → 7 PNG 输出到 /tmp/pit-mobile/
```

### 测试覆盖矩阵

| 区域 | 单测 | 集成 | E2E |
|---|---|---|---|
| Ingestion adapters | ✅ 9 | ✅ smoke | — |
| Normalization / Resolver | ✅ | ✅ | — |
| PIT builder | ✅ | ✅ | — |
| API 路由 | ✅ 18 | ✅ curl | ✅ puppeteer |
| LLM provider | ✅ 14 (mock + 9 unit + 1 live) | ✅ curl | ✅ puppeteer |
| Validator | ✅ 3 | ✅ | ✅ |
| Frontend components | ✅ 32 | ✅ | ✅ 7 screenshots |

---

## 附录 A: 关键文件

```
src/pit_market/
├── api/
│   ├── main.py                 FastAPI app + lifespan
│   ├── panels.py               /v1/panels/*
│   ├── analyses.py             /v1/analyses/* (含 _resolve_panel)
│   ├── lineage.py              /v1/lineage/*
│   └── export.py               /v1/export/*
├── ingestion/adapters/         9 个上游数据适配器
├── normalization/
│   ├── resolver.py             canonical_symbol 映射
│   └── silver.py               双时间戳观测
├── pit/builder.py              PitPanelBuilder (核心)
├── llm/
│   ├── adapter.py              LLMAdapter + 3 providers
│   └── validator.py            JSON schema + evidence_ids 校验
├── evidence/catalog.py         Evidence catalog 构建
├── data/trading_calendar.py    美东交易日历
├── storage/registry.py         Instrument/Metric/Schema 注册表
└── cli.py                      Typer CLI

frontend/
├── app/                        10 路由 (见 §7.1)
├── components/                 14 组件 (见 §7.2)
├── lib/api.ts                  API client + postJsonWithError
├── lib/formatting.ts           时区 / 日期 / 数字格式化
├── stores/sliceStore.ts        Zustand store
└── scripts/e2e-screenshots.cjs Puppeteer E2E

docker/
├── Dockerfile.api              Python 镜像 (3 stage + non-root)
├── Dockerfile.web              Next.js 镜像 (3 stage + non-root + curl)
└── README.md                   Admin 验证 runbook

scripts/
├── dev-start.sh                Native 启动 (8700/8701)
├── dev-stop.sh                 Native 停止
├── cron-watchdog.sh            Native 栈 watchdog
├── cron-watchdog-docker.sh     Docker 栈 watchdog
└── setup-env-docker.sh         Secrets 注入 .env.docker
```

---

## 附录 B: 已知约束 / 未来工作

- **真实历史数据接入**: 仓库里的 `data/gold/pit_panels/` 是 CLI 一次性生成的 manifest-only 面板,真正接 Yahoo/Polygon historical parquet 是下一步
- **DuckDB backend**: 当前 builder 走 in-memory Polars,大 universe (>500 symbols) 需要切到 DuckDB
- **生产模式验证**: `npm run build` + `next start` 完整 prod mode 还没在 CI 跑过
- **CI/CD**: E2E screenshot harness 是手动的,可加 GitHub Actions
- **OpenAPI 文档**: `/docs` Swagger UI 已可访问,但 README 里 curl examples 可再扩

---

**Maintainer**: raymodny-ai · **License**: TBD · **Last updated**: 2026-07-24