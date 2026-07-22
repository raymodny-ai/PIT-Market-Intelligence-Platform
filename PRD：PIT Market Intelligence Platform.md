<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# PRD：PIT Market Intelligence Platform

**项目名称：** `pit-market-intelligence`
**版本：** v1.1
**状态：** 产品需求文档
**主要语言：** Python 3.11+、TypeScript
**首期覆盖：** 美股、ETF、美国期货、波动率、黄金、白银
**核心能力：** Point-in-Time 数据仓、自动 ETL、可审计 LLM 分析、动态交互式报告与切片查询。

本项目从公开金融数据源构建不可变 Raw、双时间 Silver、可重算 Feature 和按决策时点生成的 PIT Panel，并在此基础上产生带字段级证据引用的 LLM 市场分析。前端不是静态 HTML 导出物，而是可按标的、时间、因子、数据源、频率、质量状态和情景实时切片的交互式研究工作台。FRED/ALFRED 提供 real-time period 机制，反映宏观序列历史观测会被修订，因此系统必须同时保存观察期、发布/可得时间和版本有效期。[^1]

***

## 一、产品目标

### 1.1 核心目标

```text
公开数据源
  ↓
Raw 原始文件不可变归档
  ↓
Silver 双时间观测表
  ↓
Gold PIT 特征表
  ↓
PIT Panel 宽表与字段级血缘
  ↓
Evidence Catalog
  ↓
LLM 结构化分析 + 证据标签
  ↓
动态报告 / 交互切片 / API / 回测导出
```

系统必须：

1. 支持日频、周频、月频、季频和事件频金融数据。
2. 支持任意 `decision_time` 的 Point-in-Time Panel 重建。
3. 严格使用 `available_at <= decision_time` 防止前视偏差。
4. 支持 FRED/ALFRED 修订数据、CFTC 周度持仓、FINRA 场外短卖、SEC 披露等异步数据。
5. 使每条 LLM 结论可以追踪至其证据字段、特征、标准化观测、Raw 文件和源请求。
6. 提供前端切片、联动图表、回放、钻取和报告动态渲染。
7. 使任何报告都可从固定的 `panel_id + panel_sha256` 重放。
8. 将所有确定性计算保留在 ETL/Feature/Rule 层，LLM 仅做受证据约束的解释。

### 1.2 非目标

MVP 不包括：

- 逐笔成交、NBBO、Level 2/Level 3 完整订单簿。
- 自动下单、券商 API 和实盘执行。
- 将 FINRA short volume 解释为 short interest 或净空仓。
- 将 COT 或 13F 描述为实时机构仓位。
- 允许 LLM 自行访问外部网页、修改数据或运行交易策略。
- 用今天的修订宏观数据回测过去。
- 将动态报告视为数据源；前端只消费冻结的 PIT 数据资产。

***

## 二、用户与场景

| 用户 | 场景 | 核心问题 | 主要输出 |
| :-- | :-- | :-- | :-- |
| 量化研究员 | 历史回测 | 当时真实可用的数据是什么？ | PIT DataFrame、特征与血缘 |
| 风险分析人员 | 每日扫描 | 哪些标的出现跨因子风险确认？ | 风险热图、事件、LLM 解释 |
| 商品研究员 | 金银仓位 | COT、ETF、美元、实际利率是否形成拥挤？ | COT 面板、宏观联动、情景 |
| ETF/期权研究员 | QQQ/SPY 风险 | 场外短卖、VXN-VIX、信用利差是否共振？ | 联动图、证据卡片、告警 |
| 数据工程师 | 数据健康 | 哪个源过期、失败、字段变更或质量下降？ | Source health、运行日志 |
| 审计/复盘人员 | 结论追踪 | 一条 LLM 结论凭什么得出？ | Finding → Evidence → Raw 血缘图 |


***

## 三、数据源范围

| 类别 | 数据源 | 数据 | 频率 | MVP 优先级 |
| :-- | :-- | :-- | :-- | :-- |
| 价格与成交量 | Yahoo Finance Adapter | OHLCV、ETF/期货价格 | 日频 | P0 |
| 期货仓位 | CFTC Public Reporting | COT 多空、套利、OI、周变化 | 周频 | P0 |
| 场外短卖 | FINRA Reg SHO | short volume、short exempt、total volume | 日频 | P0 |
| 宏观风险 | FRED / ALFRED | 利率、实际利率、信用利差、VIX 等 | 日/周/月 | P0 |
| 场外交易 | FINRA OTC Transparency | ATS/non-ATS 成交量、金额、笔数 | 周频 | P1 |
| 波动率期货 | Cboe CFE | VIX futures volume、OI | 日频 | P1 |
| 机构披露 | SEC EDGAR | 13F、13D/G、Form 4、8-K | 事件/季频 | P1 |
| ETF 申赎代理 | 基金发行方数据 | shares outstanding、holdings、AUM | 日/周 | P1 |
| 新闻情绪 | 可插拔新闻源 | 标题、事件、主题、情绪 | 事件 | P2 |


***

## 四、核心设计原则

### 4.1 PIT 时间因果

数据可用于某一决策时点的条件：

$$
available\_at \le decision\_time
$$

禁止只用：

$$
observation\_time \le decision\_time
$$

因为观察期早于决策时点不代表市场当时已经知道它。

### 4.2 Append-only 与版本化

- Raw 文件永不覆盖。
- Silver 观测值的修订以新行追加。
- Feature 重算生成新 `feature_version`。
- PIT Panel 重建生成新 `panel_version`。
- LLM 分析绑定不可变 `panel_id` 和 `catalog_id`。
- 报告只能引用冻结资产，不可隐式读取“最新数据”。


### 4.3 前后端职责分离

| 后端负责 | 前端负责 |
| :-- | :-- |
| 抓取、标准化、PIT 对齐 | 选择切片与可视化状态 |
| 特征、Z-score、分位数、规则 | 渲染数值、图表、表格与证据 |
| 质量、时间因果、血缘 | 发送筛选参数、显示筛选结果 |
| LLM Packet、Schema 校验 | 展示 LLM finding 及可展开证据 |
| 权限、缓存、分页、聚合 | 本地 UI state、联动、导出请求 |

前端**不得**重新计算 PIT 特征、自由前向填充或自行组合字段；任何研究数值必须由后端 PIT 查询或已物化 Panel 返回。

### 4.4 LLM 受控分析

- LLM 只消费 Evidence Catalog。
- 每条 finding 必须引用合法 `evidence_id`。
- 输出必须符合 JSON Schema。
- 输出须通过 evidence、质量和 PIT 验证。
- LLM 不得制造数据、来源、日期或因果结论。
- 研究结论默认采用关联性语言：“可能”“一致于”“需要确认”。

***

# 五、总体架构

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Dagster Orchestration                              │
│             schedules / sensors / partitions / backfills / checks            │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
      ┌────────────────────────────────▼─────────────────────────────────┐
      │ Source Adapters: CFTC / FINRA / FRED-ALFRED / SEC / Cboe / YF    │
      └────────────────────────────────┬─────────────────────────────────┘
                                       │
      ┌────────────────────────────────▼─────────────────────────────────┐
      │ Raw / Bronze: 原始响应、headers、request、manifest、hash         │
      └────────────────────────────────┬─────────────────────────────────┘
                                       │
      ┌────────────────────────────────▼─────────────────────────────────┐
      │ Silver: observations_bitemporal                                  │
      │ observation_time / release_time / available_at / valid interval  │
      └────────────────────────────────┬─────────────────────────────────┘
                                       │
      ┌────────────────────────────────▼─────────────────────────────────┐
      │ Gold Features: feature_observations_bitemporal                   │
      │ scores / states / quality / feature lineage                      │
      └────────────────────────────────┬─────────────────────────────────┘
                                       │
      ┌────────────────────────────────▼─────────────────────────────────┐
      │ PIT Panel Builder + Evidence Catalog + Event Engine              │
      └───────────────┬───────────────────────────────────┬─────────────┘
                      │                                   │
      ┌───────────────▼───────────────┐       ┌───────────▼─────────────┐
      │ LLM Structured Analysis        │       │ FastAPI Query Service   │
      │ schema + provenance validation │       │ slices / drilldown      │
      └───────────────┬───────────────┘       └───────────┬─────────────┘
                      │                                   │
      ┌───────────────▼───────────────────────────────────▼─────────────┐
      │ React/Next.js Dynamic Report UI                                   │
      │ Cross-filter / time replay / drilldown / evidence lineage        │
      └─────────────────────────────────────────────────────────────────┘
```

Dagster 的 OpenLineage 集成可发出以资产为中心的 lineage 事件，包括 schema、column lineage、data quality assertions 和分区时间信息，适合记录从 ETL 到报告的全链路资产依赖。[^2]

***

# 六、技术栈

| 层级 | 推荐技术 | 作用 |
| :-- | :-- | :-- |
| 编排 | Dagster OSS | 资产、调度、传感器、回填、质量门禁 |
| 存储 | Parquet + DuckDB | 不可变文件、PIT SQL、窗口与切片查询 |
| 表处理 | Polars + pandas | 解析、特征与研究导出 |
| 数据验证 | Pandera + Dagster Asset Checks | schema、范围、PIT 因果、陈旧度 |
| 后端 API | FastAPI + Pydantic v2 | 查询、数据契约、鉴权、导出 |
| 流式状态 | SSE | ETL、LLM、报告渲染进度 |
| 前端 | Next.js + React + TypeScript | 动态工作台与报告路由 |
| 图表 | Plotly.js | 时间序列、热图、散点、联动选择 |
| 数据表格 | AG Grid Community | 虚拟滚动、排序、筛选、列选择 |
| 前端状态 | Zustand 或 Redux Toolkit | 全局切片、选择、图表交互状态 |
| API 数据缓存 | TanStack Query | 查询缓存、失效、请求去重 |
| 血缘 | OpenLineage + 自定义 Facet | Dataset/Run/Field/Finding 血缘 |
| LLM | OpenAI/Gemini/Local Adapter | 受 JSON Schema 约束的分析 |
| 报告模板 | React SSR + HTML export | 动态页面与冻结静态快照 |

Plotly 支持图表同时作为交互输入和输出，可将 hover、click、框选等事件绑定为跨图表筛选条件；这正适合用于时间序列、热图、散点和指标表之间的交叉过滤。[^3][^4]

***

# 七、项目目录

```text
pit-market-intelligence/
├── README.md
├── PRD.md
├── pyproject.toml
├── .env.example
├── docker-compose.yml
├── config/
│   ├── settings.yaml
│   ├── instruments.yaml
│   ├── metrics.yaml
│   ├── availability_rules.yaml
│   ├── data_sources.yaml
│   ├── llm_prompts.yaml
│   └── schemas/
│       ├── observation.schema.json
│       ├── evidence.schema.json
│       ├── llm_analysis.schema.json
│       ├── api_slice.schema.json
│       ├── ui_view_state.schema.json
│       └── LLMProvenanceRunFacet.json
├── data/
│   ├── raw/
│   ├── silver/
│   ├── gold/
│   ├── metadata/
│   └── reports/
├── src/
│   └── pit_market/
│       ├── ingestion/
│       ├── normalization/
│       ├── features/
│       ├── pit/
│       ├── evidence/
│       ├── llm/
│       ├── lineage/
│       ├── storage/
│       ├── reporting/
│       ├── api/
│       └── dagster/
├── frontend/
│   ├── package.json
│   ├── next.config.ts
│   ├── app/
│   │   ├── dashboard/page.tsx
│   │   ├── reports/[reportId]/page.tsx
│   │   ├── panels/[panelId]/page.tsx
│   │   ├── findings/[findingId]/page.tsx
│   │   └── lineage/[entityId]/page.tsx
│   ├── components/
│   │   ├── filters/
│   │   ├── charts/
│   │   ├── tables/
│   │   ├── evidence/
│   │   ├── reports/
│   │   ├── lineage/
│   │   └── layout/
│   ├── stores/
│   │   ├── sliceStore.ts
│   │   ├── selectionStore.ts
│   │   └── reportStore.ts
│   ├── lib/
│   │   ├── api.ts
│   │   ├── queryKeys.ts
│   │   ├── formatting.ts
│   │   └── chartTransforms.ts
│   └── types/
│       └── api.ts
├── tests/
│   ├── backend/
│   ├── frontend/
│   ├── integration/
│   ├── fixtures/
│   └── snapshots/
└── notebooks/
```


***

# 八、数据模型

## 8.1 Instrument Registry

| 字段 | 示例 |
| :-- | :-- |
| `canonical_symbol` | `GOLD_COMEX` |
| `asset_class` | `commodity_future` |
| `primary_market` | `COMEX` |
| `vendor_symbol_yfinance` | `GC=F` |
| `cftc_market_code` | `088691` |
| `related_etfs` | `["GLD", "IAU"]` |
| `timezone` | `America/New_York` |
| `registry_version` | `registry.v1.0` |

首期标的：

```text
SPY, QQQ, IWM, GLD, IAU, SLV
GC=F, SI=F
GOLD_COMEX, SILVER_COMEX
VIX, VXN
```


## 8.2 Metric Registry

| 字段 | 示例 |
| :-- | :-- |
| `field_name` | `position__cftc__managed_money_net` |
| `display_name_zh` | 管理基金净持仓 |
| `source_name` | `cftc` |
| `frequency` | `weekly` |
| `unit` | `contracts` |
| `availability_rule_id` | `cftc_friday_release` |
| `max_staleness` | `10D` |
| `forward_fill_allowed` | `true` |
| `semantic_warning` | 周度仓位数据，不代表实时资金流 |
| `feature_definition_id` | `managed_money_net.v1` |

## 8.3 双时间观测表

```sql
CREATE TABLE observations_bitemporal (
    observation_id UUID PRIMARY KEY,

    source_name VARCHAR NOT NULL,
    dataset_name VARCHAR NOT NULL,
    canonical_symbol VARCHAR,
    field_name VARCHAR NOT NULL,
    value DOUBLE,
    unit VARCHAR,
    frequency VARCHAR NOT NULL,

    observation_time TIMESTAMPTZ NOT NULL,
    observation_end_time TIMESTAMPTZ,

    release_time TIMESTAMPTZ,
    available_at TIMESTAMPTZ NOT NULL,

    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,

    ingested_at TIMESTAMPTZ NOT NULL,
    run_id VARCHAR NOT NULL,
    raw_record_hash VARCHAR NOT NULL,
    parser_version VARCHAR NOT NULL,
    source_url VARCHAR,
    source_metadata_json JSON,

    quality_status VARCHAR NOT NULL,
    quality_flags_json JSON
);
```


## 8.4 Feature 表

```sql
CREATE TABLE feature_observations_bitemporal (
    feature_observation_id UUID PRIMARY KEY,

    canonical_symbol VARCHAR NOT NULL,
    field_name VARCHAR NOT NULL,
    value DOUBLE,
    unit VARCHAR,

    feature_time TIMESTAMPTZ NOT NULL,
    available_at TIMESTAMPTZ NOT NULL,
    valid_from TIMESTAMPTZ NOT NULL,
    valid_to TIMESTAMPTZ,

    feature_definition_id VARCHAR NOT NULL,
    feature_version VARCHAR NOT NULL,
    configuration_hash VARCHAR NOT NULL,

    input_observation_ids_json JSON NOT NULL,
    input_max_available_at TIMESTAMPTZ NOT NULL,

    quality_status VARCHAR NOT NULL,
    quality_flags_json JSON,
    run_id VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
```


## 8.5 PIT Panel Registry

```sql
CREATE TABLE pit_panel_registry (
    panel_id VARCHAR PRIMARY KEY,
    decision_time TIMESTAMPTZ NOT NULL,
    input_cutoff_time TIMESTAMPTZ NOT NULL,
    panel_version VARCHAR NOT NULL,

    universe_version VARCHAR NOT NULL,
    instrument_registry_version VARCHAR NOT NULL,
    metric_registry_version VARCHAR NOT NULL,
    feature_version VARCHAR NOT NULL,

    panel_path VARCHAR NOT NULL,
    panel_sha256 VARCHAR NOT NULL,
    lineage_path VARCHAR NOT NULL,

    row_count BIGINT NOT NULL,
    field_count BIGINT NOT NULL,
    quality_status VARCHAR NOT NULL,
    quality_score DOUBLE,

    dagster_run_id VARCHAR,
    git_commit_sha VARCHAR NOT NULL,
    config_hash VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);
```


***

# 九、Raw 到 PIT Panel ETL

## 9.1 文件布局

```text
data/
├── raw/
│   └── source=finra/
│       └── dataset=regsho_daily/
│           └── ingest_date=2026-07-20/
│               └── run_id=20260720T223001Z_7a12/
│                   ├── request.json
│                   ├── response.json.gz
│                   ├── response_headers.json
│                   └── manifest.json
├── silver/
│   └── observations_bitemporal/
│       └── source_name=finra/
│           └── dataset_name=regsho_daily/
│               └── available_date=2026-07-20/
│                   └── part-000.parquet
├── gold/
│   ├── features_bitemporal/
│   │   └── feature_group=short_flow/
│   │       └── available_date=2026-07-20/
│   └── pit_panels/
│       └── decision_date=2026-07-20/
│           └── decision_clock=1805_ET/
│               └── panel_version=v1/
│                   ├── market_panel.parquet
│                   ├── panel_lineage.parquet
│                   ├── quality_report.json
│                   └── manifest.json
```


## 9.2 ETL 资产图

```text
instrument_registry
metric_registry
trading_calendar
       │
       ├── raw_yfinance_daily
       ├── raw_finra_regsho
       ├── raw_fred_alfred
       ├── raw_cftc_cot
       ├── raw_finra_otc
       ├── raw_sec_edgar
       └── raw_cboe_cfe
                 │
                 ▼
     normalized_observations_bitemporal
                 │
       ┌─────────┼────────────┬─────────────┐
       ▼         ▼            ▼             ▼
price_features  flow_features macro_features positioning_features
       │         │            │             │
       └─────────┴────────────┴─────────────┘
                           │
                           ▼
            feature_observations_bitemporal
                           │
                           ▼
                    pit_panel_daily
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        market_events evidence_catalog panel_lineage
                           │
                           ▼
                    llm_market_analysis
                           │
                           ▼
              validated_analysis + report_snapshot
```


## 9.3 可得时间解析

```python
class AvailabilityResolver:
    def resolve(
        self,
        source_name: str,
        dataset_name: str,
        observation_time: pd.Timestamp,
        source_release_time: pd.Timestamp | None,
        ingested_at: pd.Timestamp,
        metadata: dict,
    ) -> tuple[pd.Timestamp, str]:
        """返回 available_at 和 availability_type。"""
```

优先级：

```text
1. 官方发布时间
2. 发布日历
3. 配置的保守规则
4. 文件检测时间
5. 实际抓取时间
```


## 9.4 PIT Panel 查询

```sql
WITH eligible AS (
    SELECT
        canonical_symbol AS symbol,
        field_name,
        value,
        unit,
        observation_time,
        release_time,
        available_at,
        ingested_at,
        quality_status,
        run_id,
        raw_record_hash,
        feature_version,
        ROW_NUMBER() OVER (
            PARTITION BY canonical_symbol, field_name
            ORDER BY available_at DESC, ingested_at DESC
        ) AS rn
    FROM feature_observations_bitemporal
    WHERE available_at <= $decision_time
      AND valid_from <= $decision_time
      AND (valid_to IS NULL OR valid_to > $decision_time)
      AND canonical_symbol IN (SELECT * FROM UNNEST($symbols))
)
SELECT *
FROM eligible
WHERE rn = 1;
```

PIT Panel 输出包括：

```text
value_panel
lineage_panel
quality_report
panel_manifest
```

`value_panel`：

```text
decision_time                symbol  price__yf__close  flow__finra__short_ratio
2026-07-20 18:05:00-04:00    QQQ           615.24                         0.473
```

`lineage_panel`：

```text
decision_time                symbol field_name                        available_at                 age_hours quality_status
2026-07-20 18:05:00-04:00    QQQ    flow__finra__short_ratio         2026-07-20 18:02:00-04:00      0.05 VALID
```


## 9.5 质量门禁

| 层级 | 关键检查 |
| :-- | :-- |
| Raw | HTTP 状态、文件 hash、响应大小、重复响应 |
| Silver | schema、单位、主键、标的映射、时间因果、范围 |
| Feature | 输入最大可得时间、窗口样本数、输出范围、血缘字段 |
| PIT Panel | `available_at <= decision_time`、陈旧度、覆盖率、Panel hash |
| LLM | JSON Schema、evidence ID、质量、PIT、限制语义、置信度上限 |
| 前端 API | 参数白名单、查询范围、Panel 不可变性、切片权限 |


***

# 十、动态报告渲染机制

## 10.1 设计目标

动态报告必须同时满足：

- **可复现**：用户可以查看某个历史固定 Panel 的报告。
- **可交互**：用户可以改变标的、日期、字段、状态、数据源和图表视图。
- **不破坏 PIT**：任何切片都明确关联 `panel_id` 或显式 `decision_time`。
- **可审计**：每一张图、每一个指标卡、每一条 finding 都显示其来源与版本。
- **高性能**：不将完整 Panel、全量 Raw 或多年高维数据一次性发送到浏览器。
- **可导出**：可导出当前筛选状态为 CSV、Parquet、PNG、HTML 或不可变报告快照。


## 10.2 两类报告模式

| 模式 | URL 示例 | 数据约束 | 用途 |
| :-- | :-- | :-- | :-- |
| 冻结报告模式 | `/reports/{report_id}` | 绑定固定 `panel_id`、`catalog_id`、`analysis_run_id` | 审计、分享、复盘、归档 |
| 动态研究模式 | `/dashboard?as_of=latest` | 用户可切换 Panel、时间、标的和字段 | 日常研究、探索、切片 |
| 历史回放模式 | `/dashboard/replay?start=...&end=...` | 每个时间点按 PIT 重建或读取已物化 Panel | 回测检查、事件复盘 |
| 结论审计模式 | `/findings/{finding_id}` | 固定结论与其证据链 | LLM 解释验证 |

冻结报告不可被动态筛选“改写”其历史结论；动态研究页可创建新的临时视图，但必须展示正在使用的 Panel/决策时点。

## 10.3 前端页面结构

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ Header: Universe | PIT Decision Time | Panel Version | Data Quality      │
├───────────────┬─────────────────────────────────────────────────────────┤
│ Filter Rail   │ Main Content                                             │
│               │                                                         │
│ - Symbol      │ KPI Cards: Price / Stress / Positioning / Data Quality  │
│ - Asset Class │                                                         │
│ - Date Range  │ Regime Timeline + Market Stress Chart                   │
│ - Decision    │                                                         │
│   Clock       │ Cross-factor Heatmap + Factor Distribution              │
│ - Domains     │                                                         │
│ - Sources     │ LLM Findings + Evidence Tags                            │
│ - States      │                                                         │
│ - Quality     │ Drilldown Table / Data Lineage Drawer                   │
│ - Frequency   │                                                         │
└───────────────┴─────────────────────────────────────────────────────────┘
```

页面主区域按功能划分：

1. **PIT Context Bar**：显示 `decision_time`、`panel_id`、`panel_version`、`panel_sha256`、特征版本、最后更新和质量状态。
2. **Universe Selector**：标的、资产类别、市场和预设 watchlist。
3. **KPI Cards**：价格、收益、压力分数、仓位分数、短卖分数、质量分数。
4. **Regime Timeline**：风险状态、关键事件、数据发布点、LLM finding 标记。
5. **Factor Explorer**：时间序列、分位数、Z-score、横截面排名。
6. **Cross-factor Matrix**：标的 × 指标域的热图。
7. **Evidence Explorer**：finding、evidence、字段可得时间和数据局限。
8. **Lineage Drawer**：从 finding 下钻至 Raw manifest。
9. **Data Health Panel**：源新鲜度、缺失率、陈旧度、错误与质量检查。
10. **Export / Snapshot**：导出当前 slice 或将当前研究视图保存为可复现报告。

***

# 十一、切片交互方案

## 11.1 Slice 定义

一个前端切片不是任意 SQL，而是受 schema 约束的查询对象。

```typescript
type SliceRequest = {
  panelId?: string;
  asOf?: string;
  decisionClock?: "1605_ET" | "1805_ET";
  universe: string[];

  dateRange?: {
    start: string;
    end: string;
  };

  domains?: Array<
    "price" | "position" | "flow" | "otc" | "macro" | "volatility" | "quality"
  >;

  fields?: string[];
  sources?: string[];
  frequencies?: Array<"daily" | "weekly" | "monthly" | "quarterly" | "event">;

  states?: Array<
    "LOW_EXTREME" | "LOW" | "NEUTRAL" | "HIGH" | "HIGH_EXTREME" |
    "MISSING" | "STALE" | "INFERRED_AVAILABILITY"
  >;

  quality?: {
    minScore?: number;
    includeStale?: boolean;
    includeInferredAvailability?: boolean;
  };

  aggregation?: {
    time: "raw" | "daily" | "weekly" | "monthly";
    crossSection: "none" | "mean" | "median" | "rank";
  };

  sort?: {
    field: string;
    direction: "asc" | "desc";
  };

  page?: {
    offset: number;
    limit: number;
  };
};
```

所有字段名必须通过 `metric_registry` 白名单验证；不允许直接把用户输入拼接到 SQL。

## 11.2 全局切片状态

前端使用单一 `SliceStore` 保存跨组件共享状态。

```typescript
type SliceState = {
  activePanelId: string | "latest";
  decisionTime: string;
  decisionClock: string;

  selectedSymbols: string[];
  selectedDomains: string[];
  selectedFields: string[];
  selectedSources: string[];
  selectedStates: string[];

  dateRange: { start: string; end: string };
  includeStale: boolean;
  includeInferredAvailability: boolean;

  selectedEvidenceIds: string[];
  selectedFindingIds: string[];
  selectedChartPoints: ChartSelection[];

  viewMode: "overview" | "research" | "replay" | "audit";
};
```

状态同步规则：

- URL Query Parameters 保存可分享的基本筛选条件。
- Zustand/Redux 保存临时交互，如 hover、brush、展开面板。
- 服务器返回的 `slice_id` 用于缓存和导出。
- Frozen Report 只允许有限展示操作，不允许更换 `panel_id`。
- 任何筛选状态变化都必须在顶部 PIT Context Bar 显示。

示例 URL：

```text
/dashboard?
panel_id=pit_20260720_1805_ET_v1_1e23&
symbols=QQQ,GLD&
domains=flow,volatility,macro&
states=HIGH,HIGH_EXTREME&
include_stale=false&
range=2026-01-01,2026-07-20
```


## 11.3 交叉过滤模型

交叉过滤使用“选择事件 → 统一 Filter Action → 重新查询/本地过滤 → 所有组件同步”的模式。

```text
用户框选时间序列区间
      ↓
dispatch(setDateRange)
      ↓
SliceStore 更新
      ↓
TanStack Query 生成新的 query key
      ↓
FastAPI 返回匹配的切片数据
      ↓
热图、表格、KPI、finding 列表和证据面板同步刷新
```

支持交互：


| 来源组件 | 用户动作 | 更新对象 | 影响组件 |
| :-- | :-- | :-- | :-- |
| 时间序列图 | 框选日期 | `dateRange` | 热图、表格、finding、事件 |
| 热图 | 点击单元格 | `symbol + domain/field` | 详情图、证据列表、KPI |
| 散点图 | 框选标的 | `selectedSymbols` | 所有图、表格、报告摘要 |
| 指标表 | 选择一行 | `selectedEvidenceIds` | Evidence Drawer、Lineage |
| Finding 卡片 | 点击证据标签 | `selectedEvidenceIds` | 字段详情、图中高亮 |
| Source Health | 点击数据源 | `selectedSources` | 所有图和字段表按来源过滤 |
| Data Quality 筛选 | 勾选 stale | `includeStale` | Panel、LLM finding、告警 |
| 时间回放条 | 拖动时间点 | `decisionTime` | 读取对应历史 PIT Panel |
| Lineage 图 | 点击节点 | `selectedEntity` | 元数据与原始文件信息 |

Plotly 的交叉过滤能力允许图表的 hover、click、selection 成为其他图或表的输入，而 Grid 与图也可通过筛选、排序和行选择联动。[^4][^3]

## 11.4 时间回放与 PIT Replay

时间回放必须分成两种模式：

### 已物化 Replay

适用于常用日期、生产日报和重要事件。

```text
用户移动到 2026-07-17 16:05 ET
  ↓
前端查询已有 panel_id
  ↓
后端返回固定 Parquet Panel 与报告资产
  ↓
前端渲染，零重算
```

优势：

- 快。
- 可严格复现。
- 适用于报告、审计和分享。


### 按需 PIT Replay

适用于未预先物化的历史时点。

```text
用户指定 decision_time
  ↓
后端校验时间、权限与请求配额
  ↓
DuckDB 按 available_at 查询 Silver/Feature
  ↓
物化临时 PIT Panel 或读取缓存
  ↓
生成 panel_id / panel hash
  ↓
返回动态切片
```

规则：

- 按需 PIT Panel 默认使用 `ephemeral=true`。
- 用户点击“保存快照”后才写入正式 `pit_panel_registry`。
- 临时 Panel 设置 TTL，例如 24 小时。
- 被 LLM 分析、导出或分享的 Panel 必须固化为永久资产。


## 11.5 切片层级

前端必须支持以下从粗到细的切片层级：

```text
市场整体
  → 资产类别
    → 标的池
      → 单一标的
        → 因子域
          → 指标字段
            → 单一观测
              → 数据血缘
                → Raw 原始文件
```

示例操作：

```text
全部 ETF
  → QQQ
    → 波动率域
      → VXN-VIX spread
        → 2026-07-20 的 HIGH 状态
          → feature_observation_id
            → input_observation_ids
              → Cboe 原始文件及 manifest
```


***

# 十二、动态渲染数据契约

## 12.1 Report View Model

后端不应让前端直接拼 DataFrame。应提供面向 UI 的稳定 View Model。

```json
{
  "report_context": {
    "report_id": "report_20260720_1805_QQQ_v1",
    "panel_id": "pit_20260720_1805_ET_v1_1e23",
    "panel_sha256": "sha256:...",
    "decision_time": "2026-07-20T18:05:00-04:00",
    "panel_version": "v1",
    "feature_version": "features.v1.0",
    "quality_status": "GOOD",
    "quality_score": 0.92
  },

  "kpis": [],
  "charts": [],
  "tables": [],
  "findings": [],
  "data_health": [],
  "lineage_summary": {},
  "available_filters": {}
}
```


## 12.2 Chart Spec

后端返回图表数据和语义，不直接返回硬编码前端布局。

```json
{
  "chart_id": "qqq_short_flow_timeline",
  "title_zh": "QQQ 场外短卖活动与价格",
  "chart_type": "timeseries_dual_axis",

  "dataset": {
    "slice_id": "slice_...",
    "fields": [
      "price__yf__close",
      "flow__finra__short_ratio__zscore__63d"
    ],
    "points": [
      {
        "timestamp": "2026-07-20T18:05:00-04:00",
        "price__yf__close": 615.24,
        "flow__finra__short_ratio__zscore__63d": 1.83,
        "evidence_ids": [
          "ev_qqq_short_ratio_z63_20260720_001"
        ]
      }
    ]
  },

  "encodings": {
    "x": "timestamp",
    "y_left": "price__yf__close",
    "y_right": "flow__finra__short_ratio__zscore__63d",
    "thresholds": [-2.0, -1.0, 1.0, 2.0]
  },

  "provenance": {
    "panel_id": "pit_...",
    "field_lineage_available": true
  }
}
```

前端负责将 `chart_type` 映射为 Plotly 组件；后端负责决定字段、切片与数据权限。

## 12.3 表格数据契约

大表必须服务端分页、排序、筛选。

```json
{
  "slice_id": "slice_a3b...",
  "total_rows": 1950,
  "offset": 0,
  "limit": 100,
  "columns": [
    {
      "field": "symbol",
      "title_zh": "标的",
      "type": "string"
    },
    {
      "field": "flow__finra__short_ratio__zscore__63d",
      "title_zh": "短卖占比 Z-score",
      "type": "number",
      "format": "0.00"
    },
    {
      "field": "quality_status",
      "title_zh": "质量状态",
      "type": "state"
    }
  ],
  "rows": [],
  "provenance": {
    "panel_id": "pit_...",
    "query_hash": "sha256:..."
  }
}
```


## 12.4 Data Point Tooltip

任何图表点或表格单元格 hover 时，展示：

```text
字段：FINRA 场外短卖成交占比 63 日 Z-score
数值：1.83
状态：HIGH
观察时间：2026-07-20 16:00 ET
可得时间：2026-07-20 18:02 ET
数据年龄：0.05 小时
质量：VALID
来源：FINRA Reg SHO
特征版本：short_ratio_zscore_63d.v1
证据：ev_qqq_short_ratio_z63_20260720_001
```

点击“查看血缘”后打开 Drawer，而不是跳转离开当前研究上下文。

***

# 十三、前端组件规范

## 13.1 Header 与 PIT Context Bar

必须始终显示：

```text
PIT Decision Time: 2026-07-20 18:05 ET
Panel: pit_20260720_1805_ET_v1_1e23
Version: v1
Quality: GOOD (0.92)
Features: v1.0
Data Cutoff: 2026-07-20 18:05 ET
```

状态颜色：


| 状态 | 颜色语义 |
| :-- | :-- |
| `GOOD` | 绿色 |
| `DEGRADED` | 黄色 |
| `STALE` | 橙色 |
| `PARTIAL` | 红色 |
| `REJECTED` | 深红 |
| `EPHEMERAL` | 蓝灰色 |

## 13.2 Filter Rail

筛选器必须包含：

- Universe / Watchlist
- 标的搜索
- Asset Class
- 市场
- 时间范围
- `decision_time`
- 决策时钟
- 数据频率
- 因子域
- 指标字段
- 数据源
- 状态阈值
- 质量状态
- 是否包含陈旧数据
- 是否包含推断可得时间数据
- 排序字段与方向
- 预设保存/加载

筛选器分组：

```text
Context
  - Panel / Date / Decision Time

Universe
  - Asset Class / Symbols / Watchlist

Data
  - Domains / Metrics / Sources / Frequency

Quality
  - Valid / Stale / Missing / Inferred Availability

Analysis
  - State / Z-score threshold / Percentile threshold / Event type
```


## 13.3 KPI Cards

每张卡片显示：

```text
名称
当前数值
变化（1D / 5D / 20D 或 1W / 4W）
状态
分位数或 Z-score
数据年龄
数据源
质量标签
```

KPI Card 点击行为：

- 点击卡片：设置相应 `domain` 或 `field`。
- 点击来源标签：筛选相应数据源。
- 点击质量标签：打开字段级质量详情。
- 点击数值趋势箭头：打开历史图。
- 点击证据计数：打开关联 findings。


## 13.4 图表组件

| 组件 | 目的 | 必需交互 |
| :-- | :-- | :-- |
| Regime Timeline | 风险状态随时间变化 | brush、hover、event click |
| Multi-axis Time Series | 价格与因子关系 | 字段切换、缩放、区间选择 |
| Cross-factor Heatmap | 标的 × 因子域状态 | cell click、排序、状态过滤 |
| Scatter Explorer | 因子关系与离群点 | lasso select、轴字段切换 |
| COT Positioning Chart | 多空、OI、净仓位 Z-score | 周频/日频对齐、发布点标记 |
| Data Freshness Matrix | 数据源与字段陈旧度 | source click、stale filter |
| Evidence Network | Finding → Evidence → Source 图 | node click、血缘 drilldown |
| Revision Timeline | 宏观数据 vintage/修订 | version toggle、as-known-vs-latest |
| Event Calendar | COT、宏观、SEC 发布事件 | event click、关联图高亮 |

## 13.5 Evidence Drawer

点击 finding 或证据后，侧边栏展示：

```text
Finding
  ├─ 标题、结论、置信度、限制
  ├─ evidence_id 列表
  │   ├─ 当前值、状态、时间、质量
  │   ├─ feature definition
  │   ├─ source 与语义限制
  │   └─ 查看原始血缘
  ├─ PIT 验证状态
  ├─ LLM 模型 / Prompt / Schema
  └─ 导出 JSON / 复制审计链接
```


## 13.6 Lineage Drawer

字段级血缘展示为：

```text
Finding
  ↓
Evidence Catalog Entry
  ↓
Feature Observation
  ↓
Normalized Observation
  ↓
Raw Record
  ↓
Raw Manifest / Source URL
```

每个节点显示：


| 节点 | 元数据 |
| :-- | :-- |
| Finding | `finding_id`、模型、Prompt、置信度 |
| Evidence | `evidence_id`、数值、状态、质量 |
| Feature | 定义、公式、窗口、输入 ID、版本 |
| Observation | 数据源、观察/发布/可得时间 |
| Raw | 文件路径、hash、请求 hash、抓取时间 |
| Run | Dagster run、Git SHA、配置 hash |


***

# 十四、动态报告渲染流程

## 14.1 首屏加载

```text
用户打开 /dashboard
  ↓
前端获取 latest panel registry
  ↓
前端设定 activePanelId 与 default slice
  ↓
并行请求：
  - report-context
  - KPI slice
  - heatmap slice
  - timeline slice
  - findings slice
  - data-health slice
  ↓
Skeleton UI → progressive render
  ↓
用户看到 KPI 与关键状态
  ↓
重图表、血缘和 LLM 内容按需加载
```


## 14.2 动态切片更新

```text
用户选择 GLD、SLV，日期改为过去 180 日
  ↓
SliceStore 更新
  ↓
URL 参数同步
  ↓
TanStack Query 新 key：
["panel-slice", panelId, normalizedSliceRequestHash]
  ↓
取消过期请求
  ↓
后端验证字段/范围/权限
  ↓
DuckDB 查询 Panel 或历史 Feature
  ↓
返回 slice_id、数据、hash、质量摘要
  ↓
图表与表格局部刷新
  ↓
保持用户选中的 evidence/finding，若不在结果内则显示“已被当前筛选隐藏”
```


## 14.3 LLM 分析流式渲染

对于用户触发的新分析：

```text
用户点击“基于当前切片生成分析”
  ↓
后端验证当前 slice 已绑定固定 panel_id
  ↓
若为 ephemeral panel，先固化或要求用户确认
  ↓
生成 Evidence Catalog
  ↓
创建 analysis_run_id
  ↓
前端连接 SSE：/v1/analyses/{analysis_run_id}/stream
  ↓
显示阶段：
  QUEUED → EVIDENCE_READY → LLM_RUNNING → VALIDATING → PUBLISHED
  ↓
仅在 VALIDATED 后渲染正式 finding
```

SSE 适合将服务器到浏览器的单向状态更新、日志、LLM 阶段事件和报告生成进度推送到前端；浏览器可通过 `EventSource` 接收 `text/event-stream`，并利用事件 ID 支持中断后续传。[^5][^6]

### SSE 事件格式

```json
{
  "event": "analysis_status",
  "id": "analysis_001:4",
  "data": {
    "analysis_run_id": "analysis_001",
    "status": "VALIDATING",
    "progress_pct": 85,
    "message_zh": "正在验证证据引用、PIT 时间和数据质量"
  }
}
```

可用事件：

```text
analysis_status
analysis_partial_summary
analysis_validation_error
analysis_completed
analysis_rejected
report_rendered
```

禁止在正式分析完成前将未经验证的 finding 当作报告结论展示。

## 14.4 静态快照导出

每个动态视图可导出为：


| 格式 | 内容 | 用途 |
| :-- | :-- | :-- |
| JSON | Slice Request、数据、Panel、hash、结果 | 程序复现 |
| CSV | 当前表格或切片 | Excel/研究 |
| Parquet | 当前 PIT Panel/历史切片 | 模型训练/回测 |
| PNG/SVG | 单张图 | 研究文档 |
| HTML | 冻结报告 | 分享、归档、审计 |
| PDF | HTML 打印版 | 合规留档 |

导出 manifest：

```json
{
  "export_id": "export_...",
  "panel_id": "pit_...",
  "slice_id": "slice_...",
  "slice_request_sha256": "sha256:...",
  "data_response_sha256": "sha256:...",
  "report_version": "ui.v1.0",
  "created_at_utc": "2026-07-21T04:10:00Z"
}
```


***

# 十五、API 设计

## 15.1 Panel 与 Slice API

| Endpoint | 方法 | 说明 |
| :-- | :-- | :-- |
| `/v1/panels/latest` | GET | 返回最新 Panel 元信息 |
| `/v1/panels/{panel_id}` | GET | Panel 详情、版本、质量、血缘摘要 |
| `/v1/panels/{panel_id}/slice` | POST | 按 SliceRequest 返回数据 |
| `/v1/panels/replay` | POST | 按 `decision_time` 构建/读取 PIT Panel |
| `/v1/panels/{panel_id}/export` | POST | 导出当前 slice |
| `/v1/metrics/registry` | GET | 前端可选字段和语义 |
| `/v1/instruments/registry` | GET | 标的、市场、映射和 watchlist |

## 15.2 LLM 与证据 API

| Endpoint | 方法 | 说明 |
| :-- | :-- | :-- |
| `/v1/evidence/{evidence_id}` | GET | 单项证据及字段级血缘 |
| `/v1/evidence/catalog/{catalog_id}` | GET | Evidence Catalog |
| `/v1/analyses` | POST | 基于固定 Panel/Slice 发起分析 |
| `/v1/analyses/{analysis_run_id}` | GET | 结构化分析结果 |
| `/v1/analyses/{analysis_run_id}/stream` | GET | SSE 状态与阶段事件 |
| `/v1/findings/{finding_id}` | GET | finding 内容 |
| `/v1/findings/{finding_id}/lineage` | GET | finding → raw 血缘图 |
| `/v1/reports/{report_id}` | GET | 冻结 HTML 报告 |
| `/v1/reports/{report_id}/view-model` | GET | 前端渲染 JSON |

## 15.3 数据健康与任务 API

| Endpoint | 方法 | 说明 |
| :-- | :-- | :-- |
| `/health` | GET | API 与依赖服务状态 |
| `/v1/sources/status` | GET | 源 SLA、新鲜度、错误 |
| `/v1/quality/panels/{panel_id}` | GET | Panel 质量报告 |
| `/v1/runs/{run_id}` | GET | Dagster/ETL 运行详情 |
| `/v1/backfills` | POST | 创建回填任务，需授权 |
| `/v1/backfills/{backfill_id}` | GET | 回填状态 |


***

# 十六、LLM 与数据可追溯性

## 16.1 Evidence Catalog

```json
{
  "catalog_id": "catalog_20260720_1805_QQQ_v1",
  "pit_panel_id": "pit_20260720_1805_ET_v1_1e23",
  "decision_time": "2026-07-20T18:05:00-04:00",
  "catalog_sha256": "sha256:...",

  "evidence_catalog": [
    {
      "evidence_id": "ev_qqq_short_ratio_z63_20260720_001",
      "symbol": "QQQ",
      "field_name": "flow__finra__short_ratio__zscore__63d",
      "display_name_zh": "FINRA 场外短卖成交占比 63 日 Z-score",
      "value": 1.83,
      "unit": "zscore",
      "state": "HIGH",

      "observation_time": "2026-07-20T16:00:00-04:00",
      "available_at": "2026-07-20T18:02:00-04:00",
      "age_hours": 0.05,

      "source_name": "finra",
      "dataset_name": "regsho_daily",
      "feature_observation_id": "feat_...",
      "normalized_observation_id": "obs_...",
      "raw_record_hash": "sha256:...",
      "feature_definition_id": "short_ratio_zscore_63d.v1",

      "quality_status": "VALID",
      "semantic_caveat_zh": "FINRA short volume 是卖空成交流，不等同于 short interest 或净空头仓位。"
    }
  ]
}
```


## 16.2 LLM Finding 结构

```json
{
  "finding_id": "finding_001",
  "title_zh": "科技板块相对对冲需求可能升温",
  "claim_zh": "QQQ 的场外报告短卖成交强度位于偏高区间，同时 VXN-VIX 利差抬升，两个指标共同指向科技板块相对风险溢价上升；但这不足以确认净空头仓位增加。",
  "classification": "RISK_WARNING",
  "support_type": "MULTI_FACTOR_CONFIRMATION",
  "causal_language_level": "ASSOCIATIVE_ONLY",

  "llm_confidence": 0.71,
  "final_confidence": 0.68,

  "evidence_ids": [
    "ev_qqq_short_ratio_z63_20260720_001",
    "ev_qqq_vxn_vix_20260720_002"
  ],

  "limitations_zh": [
    "FINRA 短卖成交量不等于未平仓空头。",
    "VXN-VIX 利差不是直接的收益预测指标。"
  ]
}
```


## 16.3 验证规则

```text
1. 每个 finding 至少引用一个 evidence_id。
2. 风险/方向 finding 默认需要两个不同因子域证据。
3. evidence_id 必须存在于 Catalog。
4. 所有证据均满足 available_at <= decision_time。
5. 质量不为 VALID 的证据须限制 final_confidence。
6. 特殊源语义限制必须保留。
7. schema、PIT、质量或证据校验失败则 REJECTED。
```

OpenLineage 可通过 dataset facets、列级 lineage 和 custom facets 附加输入/输出、字段关系和运行元数据；项目将此用于实现 `Finding → Evidence → Feature → Observation → Raw` 的可视化追溯。[^7][^8]

***

# 十七、前端性能与缓存策略

## 17.1 数据访问原则

- 首屏只加载 KPI、基础上下文和默认图的聚合数据。
- 大表采用 cursor/offset 分页与虚拟滚动。
- 长时间序列默认按日/周聚合，用户放大后再请求原始粒度。
- 图表使用服务端聚合，避免浏览器处理数百万点。
- 返回数据中始终带 `slice_id`、`query_hash`、`panel_id`、`panel_sha256`。
- 明确区分不可变 PIT Panel 与可失效的 `latest` 指针。


## 17.2 API 缓存键

```text
cache_key =
SHA256(
  panel_id +
  normalized_slice_request +
  api_view_version +
  user_permission_scope
)
```

缓存层：


| 层 | 缓存对象 | TTL |
| :-- | :-- | :-- |
| 浏览器 | TanStack Query response | 30-120 秒，冻结报告可无限 |
| API 内存/Redis | Slice response | 5-30 分钟 |
| DuckDB/Parquet | 物化 PIT Panel | 永久，版本化 |
| CDN | 冻结 HTML、静态资产 | 长缓存，内容 hash 文件名 |

## 17.3 Downsampling

| 场景 | 默认策略 |
| :-- | :-- |
| 5 年日频图 | 服务端下采样至 1,000-2,000 点 |
| 1 年内日频图 | 原始日频 |
| 周频 COT | 原始周频 |
| 分钟级未来扩展 | LTTB 或时间桶 OHLC 聚合 |
| 热图 | 返回当前筛选的聚合矩阵 |
| 大表 | 服务器分页，最多 500 行/页 |

下采样不得改变统计含义：

- 价格采用 OHLC 或最后值。
- 成交量采用求和。
- 比率、Z-score、分位数采用在 Gold 层预先定义的聚合逻辑。
- 所有图标注当前显示频率与聚合方式。

***

# 十八、权限与安全

| 资源 | 普通研究用户 | 管理员 |
| :-- | --: | --: |
| 查看冻结报告 | 是 | 是 |
| 查询公开 Panel Slice | 是 | 是 |
| 导出 CSV/PNG | 是 | 是 |
| 导出 Parquet | 可配置 | 是 |
| 查看 Raw 文件内容 | 否或受限 | 是 |
| 查看完整 API key/请求头 | 否 | 否 |
| 触发按需 PIT Replay | 可配置限额 | 是 |
| 触发回填 | 否 | 是 |
| 修改 Registry/Metric 定义 | 否 | 是 |
| 发起在线 LLM 分析 | 配额控制 | 是 |

安全要求：

- API Key 仅保存在环境变量或秘密管理系统。
- Raw request headers 必须脱敏后展示。
- 前端只接收经过 API 过滤后的数据。
- 所有导出与 LLM 调用记录 `user_id`、时间、Panel ID、Slice hash。
- 任何 ad-hoc SQL 接口必须禁止或仅限管理员只读白名单查询。
- HTML 分享链接默认是冻结只读快照。

***

# 十九、测试要求

## 19.1 PIT 与 ETL 测试

- CFTC 在周五发布前不可出现在 Panel。
- 13F 仅在 filing acceptance time 后生效。
- ALFRED 修订前后应返回不同 vintage。
- `available_at > decision_time` 的记录必须被排除。
- Forward-fill 超过 `max_staleness` 必须变为 `STALE` 或 `NaN`。
- 同输入、同配置、同版本重跑 Panel hash 相同。
- 解析器升级只能从 Raw 回放，不依赖当前 API 返回值。


## 19.2 LLM 血缘测试

- finding 不得引用不存在的 `evidence_id`。
- 证据质量为 `STALE` 时 final confidence 自动被 cap。
- finding 必须继承 FINRA/COT/13F 的语义限制。
- 未通过 schema 或 PIT 验证的结果不可进入报告 API。
- 每个 finding 的 lineage endpoint 能查询至 Raw manifest。


## 19.3 前端交互测试

- 改变 symbol 后所有组件使用同一 `SliceStore` 状态。
- 时间 brush 后图、表、finding 和热图同步更新。
- 点击热图单元格后字段详情和 Evidence Drawer 正确定位。
- URL 参数可完整恢复可分享的切片状态。
- 切换历史 Panel 时 Header 的 `panel_id` 和 `decision_time` 正确更新。
- Frozen report 不能通过 UI 改变其底层 `panel_id`。
- 图表 tooltip 显示 `available_at`、质量和证据 ID。
- 当请求取消或返回顺序错乱时，不得用旧响应覆盖新 slice。
- SSE 中断后可根据 event ID 重连。
- 大表筛选、排序、翻页使用服务端分页。

***

# 二十、CLI

```bash
# 初始化项目
pit-market init

# 更新数据
pit-market refresh --symbols SPY,QQQ,GLD,SLV

# 构建固定 PIT Panel
pit-market pit build \
  --decision-time "2026-07-20 18:05:00 America/New_York" \
  --symbols QQQ,GLD \
  --panel-version v1

# 按需历史重放
pit-market pit replay \
  --decision-time "2024-08-05 16:05:00 America/New_York" \
  --symbols SPY,QQQ

# 发起 LLM 分析
pit-market analyze \
  --panel-id pit_20260720_1805_ET_v1_1e23 \
  --provider openai

# 生成冻结报告
pit-market report build \
  --panel-id pit_20260720_1805_ET_v1_1e23

# 导出切片
pit-market export \
  --panel-id pit_20260720_1805_ET_v1_1e23 \
  --symbols QQQ,GLD \
  --domains flow,volatility \
  --format parquet

# 数据健康检查
pit-market healthcheck

# 回填
pit-market backfill features \
  --feature-group positioning \
  --start 2020-01-01 \
  --end 2026-07-20 \
  --feature-version v2
```


***

# 二十一、开发里程碑

## Phase 0：基础工程

- Python 项目、DuckDB、Parquet、配置、日志、Registry。
- Next.js 前端骨架、API client、SliceStore、PIT Context Bar。
- 测试、lint、pre-commit、CI。


## Phase 1：PIT 数据 MVP

- yfinance、FRED、CFTC、FINRA Reg SHO。
- Raw append-only、Silver 双时间表、Availability Resolver。
- Gold 基础特征与 PIT Panel。
- Panel API、基础表格、KPI 与时间序列图。
- PIT 防泄漏自动测试。


## Phase 2：动态切片与报告

- Slice API、服务端分页、字段白名单。
- Filter Rail、热图、时间 brush、交叉过滤。
- Frozen Report、Dynamic Dashboard、PIT Replay。
- CSV/Parquet/HTML 导出与 export manifest。


## Phase 3：LLM 可追溯分析

- Evidence Catalog、LLM Adapter、JSON Schema。
- Finding-level Evidence Drawer 与 Lineage Drawer。
- SSE 分析进度、验证与失败状态。
- HTML 报告中的证据标签和审计页脚。


## Phase 4：市场结构增强

- FINRA ATS/OTC、Cboe、SEC、ETF shares/holdings。
- Revision Timeline、事件日历、Source Health Matrix。
- OpenLineage 可视化和 lineage API。


## Phase 5：研究与生产化

- Walk-forward 回测、因子 IC、收益归因。
- XGBoost、贝叶斯网络、状态模型。
- Redis、对象存储、PostgreSQL、Docker 部署。
- 用户权限、共享 watchlist、通知与告警。

***

# 二十二、验收标准

v1.1 达标需满足：

- 对 `SPY, QQQ, GLD, SLV` 可自动生成可审计 PIT Panel。
- COT、FRED/ALFRED、FINRA、SEC 等数据按真实或保守 `available_at` 处理。
- Raw、Silver、Feature、PIT Panel、Evidence、LLM Finding 均有版本、hash 和 lineage。
- 所有回测和前端历史回放使用同一 PIT 查询逻辑。
- Dashboard 支持按标的、时间、领域、字段、数据源、质量状态、频率进行动态切片。
- 图、表、KPI、finding 和 evidence 之间实现交叉过滤。
- 每个图点和表格单元格可查看数值、观察时间、可得时间、数据年龄、质量、来源和证据。
- 每个 LLM finding 至少关联一个合法 evidence ID，并可追溯到 Raw manifest。
- Frozen Report 可稳定复现；动态研究视图可以另存为新的可审计快照。
- SSE 可展示 ETL、PIT replay 和 LLM 分析阶段，并在断线后恢复。
- 所有大表通过服务端分页，长时间序列采用服务端聚合/下采样。
- 数据源失败、陈旧、推断发布时间或 LLM 验证失败均在 UI 中明确呈现，不得静默隐藏。
<span style="display:none">[^10][^11][^12][^13][^14][^15][^16][^17][^18][^19][^9]</span>

<div align="center">⁂</div>

[^1]: https://fred.stlouisfed.org/docs/api/fred/realtime_period.html

[^2]: https://docs.dagster.io/integrations/libraries/openlineage

[^3]: https://dash.plotly.com/interactive-graphing

[^4]: https://dash.plotly.com/dash-ag-grid/crossfilter

[^5]: https://fastapi.tiangolo.com/tutorial/server-sent-events/

[^6]: https://fossies.org/linux/fastapi/docs/ko/docs/tutorial/server-sent-events.md

[^7]: https://openlineage.io/docs/spec/facets/

[^8]: https://openlineage.io/docs/spec/facets/dataset-facets/column_lineage_facet/

[^9]: https://gist.github.com/nite/aff146e2b161c19f6d553dc0a4ce3622

[^10]: https://community.plotly.com/t/crossfiltering-selectedpoints-with-filtered-dataframe-or-colored-plot/49068

[^11]: https://stackoverflow.com/questions/70869133/how-to-add-crossfiltering-across-multiple-chart-types-via-dash-plotly

[^12]: https://github.com/plotly/public-health

[^13]: https://community.plotly.com/t/cross-filtering-in-plotly-studio/93425

[^14]: https://medium.com/@upesh.jindal/server-sent-events-with-fastapi-ab9ed99ccac4

[^15]: https://mahdijafaridev.medium.com/implementing-server-sent-events-sse-with-fastapi-real-time-updates-made-simple-6492f8bfc154

[^16]: https://www3.cs.stonybrook.edu/~mueller/teaching/cse332/Dash Intro.pdf

[^17]: https://community.plotly.com/t/crossfiltering-on-timeseries-plots/4605

[^18]: https://medium.com/@pratik.bariya_67823/what-is-server-sent-events-sse-how-to-implement-sse-with-python-fastapi-0abc476f0d68

[^19]: https://medium.com/@mikez.garcia/how-to-push-data-to-the-browser-with-fastapi-and-python-using-server-sent-events-f4bc862df42a

