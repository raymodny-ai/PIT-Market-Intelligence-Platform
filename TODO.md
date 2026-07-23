# PIT Market Intelligence Platform — 项目 TODO

> **来源**:基于 `PRD：PIT Market Intelligence Platform.md` v1.1 + `PIT Market Intelligence Platform — 演化 PRD v2.0.md` 拆解
> **覆盖阶段**:Phase 0 — Phase 7(Phase 0–5 对应 PRD v1.1;Phase 6–7 对应 PRD v2.0 五大 Epic)
> **状态**:v2.0(真实数据接入 + DuckDB 存储底座 + 本地 CI/CD + OpenAPI 扩展 + CLI→前端全功能迁移)
> **维护者**:Mavis(mavis) — 阶段编排、闸门判定
> **最后更新**:2026-07-23 v2.0
> **TODO 总数**:58 条(T-01~T-54 + T-40b/T-40c,新增 T-03b;T-05 拆分为 T-05a~T-05d;v2.0 新增 T-34~T-54 共 23 条);**纪律 10 条**、**风险 15 条**、**PIT 防泄漏 case 14 条**

---

## 0. 团队与责任约定

| 角色 | ID 前缀 | 责任范围 | 不做什么 |
|:--|:--|:--|:--|
| **Mavis (mavis)** | `M-` | 阶段编排、Plan 拆分、闸门准入判定、跨阶段决策、对外同步 | 不写业务代码;不做具体实现 |
| **Coder** | `C-` | 全部工程实现(后端 ETL/特征/数据仓、FastAPI、Next.js 前端、LLM Adapter、CLI、血缘、OpenLineage);PIT 防泄漏测试的**测试框架 + case 骨架** | 不自检;不绕过闸门;不单独准备 PIT 防泄漏 fixture |
| **Verifier** | `V-` | 每个 Phase 末尾的独立验证;PIT 防泄漏、面板重建 hash、血缘回溯、UI 行为、LLM finding 验证;为 PIT 防泄漏补充**adversarial case** | 不写代码、不加项目测试(只对项目目录);不写 fixture;可写 `/tmp` 临时脚本验证 |
| **General** | `G-` | 配置文件、CI 脚本、文档、notebook、调研、数据健康/告警、导出 manifest 模板;**PIT 防泄漏测试的 fixture 数据构造**(伪造 future-available 观测) | 不参与核心 ETL/前端业务逻辑;不写验证规则本身 |

**核心纪律**

1. 每个 Phase 末尾必有 `V-XX` 闸门,闸门未通过不进入下一阶段。
2. PIT 防泄漏自动测试与 ETL 同步写,不后补。
3. **PIT 防泄漏测试责任三角**:`Coder` 写测试框架与 case 骨架 → `General` 准备 fixture 数据(伪造的 future-available 观测、修订前 vintage、跨源冲突等)→ `Verifier` 补充 adversarial case 并独立复跑。Coder 不准备 fixture,General 不写断言,Verifier 不写测试文件。
4. LLM 验证流水线(Schema + 证据 + PIT + 质量 cap + 语义限制)优先级高于 Prompt 优化。
5. Verifier 必须独立复现,不复读 Producer 的 diff/报告。
6. Raw 永远不覆盖;Silver 修订以新行追加,每条 Silver 记录带 `fill_type: OBSERVED | FORWARD_FILLED | INTERPOLATED`;Feature 重算生成新 `feature_version`;Panel 重建生成新 `panel_version`。
7. **数据源语义警告必须自下而上传播**:Source → Silver `quality_flags_json` → Feature `quality_flags_json` → Evidence `semantic_caveat_zh` → LLM Finding `limitations_zh`。任意一层丢失则 Verifier 闸门 FAIL。
8. **PIT 字段精度与 API 路由硬性规则**(避免静默前视偏差):
   - `available_at` 必须为 `TIMESTAMPTZ` 精确到分钟(纯日期不允许),跨 DST 自动切换
   - **FRED 必须经 ALFRED 调用**(必传 `realtime_start=ingest_date`),**禁止**直接调 FRED 主 API 拿最新修订值
   - **canonical_symbol 必须注册**:未在 Instrument Registry 的 symbol 写入 Silver 时,Pandera 拒绝 + 报 `UNMAPPED_SYMBOL`;原始 vendor symbol 保存在 `source_metadata_json.vendor_symbol`
   - **多源分母同源**:计算 `flow__finra__short_ratio` 等比率特征,分子分母必须同源,不得混入其他数据源
   - **期货展期事件由 Adapter 暴露,Feature 层消费**:`detect_roll_events()` 是 T-05a Adapter 接口,T-08 特征层调用;Silver 层不处理展期
9. **v2.0 存储后端透明性**(避免业务代码与存储引擎耦合):
   - 所有业务层必须通过 `StorageBackend` Protocol 访问数据,禁止直接 import `duckdb` 或 `polars` IO
   - `PIT_STORAGE_BACKEND=duckdb|polars` 环境变量切换,小数据集本地开发仍可用 Polars
   - `/api/v1/sql` 端点**仅限开发模式**(`ENV=development`),生产模式必须关闭;Polygon API key 通过 `.env` 注入,不得硬编码
10. **v2.0 CLI→前端功能等价性**(保证 UI 成为一等公民):
    - CLI 保留为高级/脚本用途,v2 不删除任何现有 CLI 子命令(向后兼容)
    - 每个 CLI 子命令对应的功能必须在前端有完整等价实现,CLI 能做的事 UI 也必须能做
    - 所有异步任务写结构化日志(`structlog`),必含 `job_id` / `symbol` / `duration_ms`

---

## 1. 阶段总览

| Phase | 主题 | 关键交付 | 闸门 |
|:--|:--|:--|:--|
| **0** | 工程底座 | 项目骨架、Registry、CI、前后端 hello world | V-04 build/lint/test/CI 全绿 |
| **1** | PIT 数据 MVP | 4 个 P0 数据源(T-05a~d)+ Silver(含 `fill_type`)+ Gold(含窗口配置 + 语义警告传播)+ PIT Builder + 基础 API + 基础看板 | V-13 PIT 防泄漏 9 条 case + 重建 hash 一致 + 解析器回放 |
| **2** | 动态切片与报告 | Slice API、Filter Rail、交叉过滤、4 类报告、导出 | V-19 URL 恢复 / frozen 不可改 / SSE 重连 |
| **3** | LLM 可追溯分析 | Evidence Catalog、LLM Adapter、验证流水线、SSE、抽屉 | V-25 血缘可达 Raw / STALE 证据 cap |
| **4** | 市场结构增强 | P1 数据源、Revision Timeline、Source Health、OpenLineage 可视化 | V-29 陈旧/失败/推断数据 UI 显式 |
| **5** | 研究与生产化 | 回测、因子模型、Redis+PG+OSS、权限、CLI、12 条验收 | V-33 对齐 PRD 二十二 12 条 |
| **6** | v2.0 数据与存储底座升级 | 真实历史数据接入(Yahoo/Polygon)、DuckDB 存储层替换、增量更新调度、性能基准 | V-40c 真实数据面板 + DuckDB 性能达标 + 独立复现偏差≤10% + PIT 防泄漏回归 |
| **7** | v2.0 生产化与前端全功能演进 | 本地 CI/CD 脚本、OpenAPI 文档扩展、CLI→前端 UI 6 大页面全功能迁移 | V-54 本地 CI 一键通过 + 前端 6 页面功能等价 + prod build 零 error |

---

## 2. 详细 TODO

### Phase 0 — 工程底座

#### T-01 · 初始化后端项目骨架
- **阶段**:Phase 0 / 工程
- **责任**:`Coder`
- **依赖**:—
- **交付**:
  - `pyproject.toml`(Python 3.11+,依赖:Dagster、DuckDB、Polars、pandas、Pandera、FastAPI、Pydantic v2、pydantic-settings、structlog、httpx、tenacity、PyYAML)
  - 目录骨架:`src/pit_market/{ingestion,normalization,features,pit,evidence,llm,lineage,storage,reporting,api,dagster}`
  - `data/{raw,silver,gold,metadata,reports}/` + `.gitkeep`
  - `config/{settings.yaml,instruments.yaml,metrics.yaml,availability_rules.yaml,data_sources.yaml,llm_prompts.yaml}`
  - `config/schemas/{observation,evidence,llm_analysis,api_slice,ui_view_state}.schema.json` + `LLMProvenanceRunFacet.json`
  - `.env.example`(API key 占位,无真实密钥)
  - `docker-compose.yml`(Dagster daemon + Webserver + DuckDB volume)
- **验收**:
  - `pip install -e .` 可执行
  - `python -c "import pit_market"` 通过
  - `ruff check` 与 `mypy` 通过

#### T-02 · 搭建 Next.js 前端骨架
- **阶段**:Phase 0 / 工程
- **责任**:`Coder`
- **依赖**:—
- **交付**:
  - `frontend/`(Next.js 14 App Router + TypeScript strict)
  - 依赖:zustand、@tanstack/react-query、plotly.js、ag-grid-community、zod
  - 路由占位:`/dashboard`、`/reports/[reportId]`、`/panels/[panelId]`、`/findings/[findingId]`、`/lineage/[entityId]`
  - 通用组件:`PITContextBar`(显示 panel_id/decision_time/panel_version/quality/feature_version)、`EmptyState`、`ErrorBoundary`
  - `stores/sliceStore.ts`(Zustand 全局切片状态)、`lib/api.ts`(fetch wrapper + zod 解析)、`types/api.ts`(与后端 JSON Schema 对齐)
- **验收**:
  - `pnpm dev` 启动,5 个路由均可访问
  - `pnpm build` 通过;ESLint + tsc --noEmit 通过

#### T-03 · Instrument / Metric / Schema Registry
- **阶段**:Phase 0 / 工程
- **责任**:`Coder`
- **依赖**:T-01
- **交付**:
  - `config/instruments.yaml` 注册首期标的:`SPY, QQQ, IWM, GLD, IAU, SLV, GC=F, SI=F, GOLD_COMEX, SILVER_COMEX, VIX, VXN`(含 `vendor_symbol_yfinance` / `cftc_market_code` / `related_etfs` / `timezone` / `registry_version`)
  - `config/metrics.yaml` 字段定义:含 `availability_rule_id`、`max_staleness`、`forward_fill_allowed`、`semantic_warning`、`feature_definition_id`
  - 4 个 JSON Schema:`observation.schema.json`、`evidence.schema.json`、`llm_analysis.schema.json`、`api_slice.schema.json`、`ui_view_state.schema.json` + `LLMProvenanceRunFacet.json`
  - 加载器:`src/pit_market/storage/registry.py`(YAML 解析 + 版本号校验 + Schema 校验)
- **验收**:
  - 12 个标的全部入库,字段非空
  - 5 个 Schema 通过 JSON Schema 官方校验器
  - `registry_version` 写入并可被 PIT Panel 引用

#### T-03b · Trading Calendar 初始化
- **阶段**:Phase 0 / 工程(上游资产)
- **责任**:`Coder`
- **依赖**:—
- **交付**:
  - `src/pit_market/data/trading_calendar.py`:NYSE/Nasdaq 交易日历(基于 `exchange_calendars` 库)
  - 输出:`trading_calendar` 表(交易日、是否开盘、市场节假日、提前收盘日)
  - 提供:`is_trading_day(date) → bool` / `previous_trading_day(date) → date` / `next_trading_day(date) → date` / `trading_days_between(start, end) → list[date]`
  - 支持 ET 时区,处理 DST 与提前收盘
  - 单元测试:至少覆盖元旦 / 感恩节 / 圣诞节 / 提前收盘日
- **验收**:
  - 与 NYSE 官方 2024–2026 日历逐日比对 100% 一致
  - `previous_trading_day` 在周末/节假日正确回退
  - 所有 PIT Panel 重建路径必先经过此日历
- **为什么在 Phase 0**:PRD §9.2 资产图将 `trading_calendar` 列为上游资产,T-07 AvailabilityResolver / T-09 PIT Panel Builder / T-12 防泄漏测试均依赖;非交易日 `available_at` 推算错误会直接导致前视偏差。

#### T-04 · Phase 0 闸门
- **阶段**:Phase 0 / 验证
- **责任**:`Verifier`
- **依赖**:T-01 / T-02 / T-03 / T-03b
- **交付**:`docs/phase-0-gate.md`,含 PASS/FAIL 判定 + 证据
- **验收**:
  - `pip install -e .` + `pip check`
  - `ruff check` + `mypy src` 通过
  - `pnpm install` + `pnpm build` + `pnpm lint` 通过
  - GitHub Actions CI(或本地等效)全绿
  - 前后端 hello world 联调:前端 `fetch /health` 返回 200
  - Trading Calendar 与 NYSE 官方 2024–2026 日历 100% 一致

---

### Phase 1 — PIT 数据 MVP

#### T-05a · Yahoo Finance Adapter(OHLCV)
- **阶段**:Phase 1 / 数据
- **责任**:`Coder`
- **依赖**:T-01 / T-03 / T-03b
- **交付**:
  - `src/pit_market/ingestion/adapters/yfinance.py`
  - 封装 `yfinance` 库,处理限流(指数退避 + 1 req/s 上限)
  - **可用性双时钟**(关键):每个交易日产出两版 Raw——
    - `quote_realtime`:16:05 ET 决策时钟,使用盘中延迟报价
    - `close_final`:18:05 ET 决策时钟,使用收盘后确认价
  - `decision_clock: "1605_ET" | "1805_ET"` 由调用方指定,落 Raw manifest
  - **价格类型三态**:`price_type: RAW_CLOSE | ADJ_CLOSE | SPLIT_FACTOR`
    - `RAW_CLOSE`:未经调整的收盘价(可视为基础)
    - `ADJ_CLOSE`:经股息/拆股追溯调整的收盘价(由 yfinance `auto_adjust` 派生)
    - `SPLIT_FACTOR`:拆股因子(股息/分拆事件)
  - **自然主键**:`(canonical_symbol, field_name, observation_time, price_type)` — 修订时追加新行 + 旧行 `valid_to` 标定,严格 append-only
  - **`quality_flags_json` 必含**:`adj_factor`(调整系数)/ `split_ratio`(拆股比例)/ `adjusted_at`(调整时间)
  - **新增 availability rule**:`yfinance_close_price` — `observation_time = T 日 16:00 ET(收盘时间)`,`available_at = T 日 18:00 ET`(保守,等待复权因子稳定);非交易日由 Trading Calendar 守卫,禁止写入空行
  - **期货展期事件接口**:Adapter 暴露 `detect_roll_events(series_id, start, end) -> list[RolloverEvent]`,由 T-08 特征层调用(Silver 层不处理)
- **验收**:
  - 同一标的同一日两版 Raw 落盘,`decision_clock` 字段正确
  - 限流触发后,Raw manifest 记录 `quality_status = SOURCE_THROTTLED`,Panel 允许该标的缺失但在 `quality_report.json` 显式记录
  - 限流 / 空数据 / 网络错误三种失败模式分别有 1 个单元测试
  - 重复请求得相同 hash,不入库
  - **新增**:`price_type` 三态分别落 Silver,自然主键不冲突
  - **新增**:同 `observation_time` 的 `RAW_CLOSE` 修订(如拆股事件后),Silver 出现新行 + 旧行 `valid_to` 标定
  - **新增**:非交易日(周末/节假日)调 yfinance 不得写入空行,Trading Calendar 守卫生效
  - **新增**:T-12 case 9 — "yfinance 拆股事件后,旧 RAW_CLOSE 的 `valid_to` 已被标定,Panel 重建仍可读到旧观测的 PIT 视图"

#### T-05b · FRED / ALFRED Adapter(宏观)
- **阶段**:Phase 1 / 数据
- **责任**:`Coder`
- **依赖**:T-01 / T-03 / T-03b
- **交付**:
  - `src/pit_market/ingestion/adapters/fred_alfred.py`
  - **强制调 ALFRED API 而非 FRED**(关键纪律 #8):`https://api.stlouisfed.org/fred/series/observations?realtime_start=<ingest_date>&...`,**禁止**直接调 FRED 主 API(否则拿到的是最新修订值,破坏 PIT)
  - 每次请求**必传** `realtime_start = ingest_date`(本批抓取时刻),可选 `realtime_end` 用于窗口
  - **Raw `request.json` 必含 `realtime_start` / `realtime_end` / `vintage_dates` 完整记录**(回放与审计可验证)
  - **同时支持 FRED(最新)+ ALFRED(vintage 历史)**:对每个 series 拉取 `realtime_start/observation_start/observation_end` 三元组
  - 关键字段:`vintage_date`(=数据从该日起可得的真实时间)、`observation_time`(=数据观察期)、`release_time`(官方发布时间)
  - 修订以新 Raw 落盘,旧 Raw 不覆盖(append-only)
  - **新增 availability rule**:`fred_market_proxy_t_plus_1` — 适用 FRED 代理的市场数据序列(`VIXCLS` / `DGS10` 等),与 Cboe CFE 直接获取的 VIX 期货区分;FRED 通常 T+1/T+2 更新,Panel 不得早用
  - ALFRED 的 real-time period 机制正确应用
- **验收**:
  - 同一 series 多个 vintage 全部落 Raw,文件可区分
  - Silver 层的 `valid_from / valid_to` 能正确反映 vintage 切换
  - T-12 防泄漏测试的 "ALFRED 修订前后应返回不同 vintage" case 可通过
  - 缺 `realtime_start` 时回落至 `release_time` + 配置保守规则
  - **新增**:`request.json` 必有 `realtime_start`,否则 Adapter 启动失败(单元测试覆盖)
  - **新增**:T-12 case 10 — "同一序列用 ALFRED vintage 查询 vs. FRED 最新值,两者在有修订的日期必须返回不同数值;若总是相同则说明 Adapter 错调 FRED"
  - **新增**:`VIXCLS` 经 FRED 走 `fred_market_proxy_t_plus_1` 规则,Panel 在 T+1 14:00 ET 之前不得使用当日 VIX

#### T-05c · CFTC COT Adapter(期货持仓)
- **阶段**:Phase 1 / 数据
- **责任**:`Coder`
- **依赖**:T-01 / T-03 / T-03b
- **交付**:
  - `src/pit_market/ingestion/adapters/cftc_cot.py`
  - 解析 CFTC 固定宽度文本格式(`cot_year.txt` Legacy / `disagg_cot.txt` Disaggregated / `fina_cot.txt` TFF)
  - 字段映射:
    - Legacy:`commercial_long/short/spread` / `noncommercial_long/short/spread` / `nonreportable_long/short` / `open_interest_all` / `traders_*_all`
    - Disaggregated:`producer_merchant_*` / `swap_dealer_*` / `managed_money_*` / `other_reportable_*` / `nonreportable_*`
    - TFF:`dealer_*` / `asset_manager_*` / `leveraged_funds_*` / `other_reportable_*` / `nonreportable_*`
  - 标的映射:CFTC market code(如 `088691` = Gold)→ Instrument Registry `cftc_market_code`
  - **路由(关键)**:Instrument Registry 新增字段 `cot_report_type: LEGACY | DISAGGREGATED | TFF`,Adapter 根据该字段路由到不同解析器。黄金/白银 = Disaggregated,VIX 期货 = TFF
  - **可用性规则(扩)**:`cftc_friday_release` 完整结构 —
    ```yaml
    cftc_friday_release:
      observation_day_of_week: TUESDAY
      observation_time_utc: "21:00"   # 周二收盘时点
      release_day_of_week: FRIDAY
      release_time_et: "15:30"        # 周五 15:30 ET(非开盘)
      timezone_aware: true            # DST 安全(EDT/EST 自动切换)
      lag_days: 3
      fallback: next_business_day     # 遇节假日顺延
    ```
  - **`available_at` 必须为 `TIMESTAMPTZ` 精确到分钟**(非纯日期)—— 当 `decision_time = 周五 15:00 ET` 时,COT 数据**不可**出现在 Panel(发布未完成)
- **验收**:
  - 至少 GOLD_COMEX(Disaggregated)/ SILVER_COMEX(Disaggregated)/ VIX 期货(TFF) 三类标的各解析正确
  - `cot_report_type` 在 Instrument Registry 全部 12 个标的填齐(Unknown / Missing → FAIL)
  - 解析器升级可从历史 Raw 回放,新版本产出与旧版本字段映射一致
  - T-12 防泄漏测试的 "CFTC 周五 15:30 ET 前不可出现在 Panel" case 可通过
  - **新增**:DST 切换周(3 月 / 11 月)日期正确,无 ±1h 偏差
  - **新增**:CFTC 节假日顺延规则生效(感恩节后周五 = 周六才发,顺延至下周一)

#### T-05d · FINRA Reg SHO Adapter(场外短卖)
- **阶段**:Phase 1 / 数据
- **责任**:`Coder`
- **依赖**:T-01 / T-03 / T-03b
- **交付**:
  - `src/pit_market/ingestion/adapters/finra_regsho.py`
  - 解析 FINRA Reg SHO 日度短卖成交量(`short_volume` / `short_exempt` / `total_volume`)
  - 标的映射:FINRA symbol → Instrument Registry `canonical_symbol`(SPY/QQQ/IWM/GLD/IAU/SLV)
  - **可用性规则(重命名)**:从 `finra_regsho_t_plus_1` → **`finra_regsho_t_plus_1_afternoon`** — `available_at = observation_date + 1 营业日 + 14:00 ET`(取保守估计,覆盖部分市场 NYSE Arca 在 T+2 才出现的延迟);`max_staleness = 2D`(允许跨周末最多 2 日陈旧)
  - **关键**:T 日 18:05 的 Panel **不得**包含 T 日的 FINRA Reg SHO 数据
  - **语义警告(关键)**:Metric Registry `flow__finra__short_ratio` 字段的 `semantic_warning` 改为 ——"short_ratio 分母为 FINRA reporting venue 成交量,**非全市场 consolidated volume**,不得直接与基于 SIP tape 的成交占比对比"。特征层计算时优先用同源 `total_volume`;Evidence 层 `semantic_caveat_zh` 标注;T-22 LLM 验证规则第 6 条覆盖该语义约束
  - T-12 防泄漏测试增加专项 case 11:"T 日 18:05 的 Panel 不得包含 T 日的 FINRA Reg SHO 数据"
- **验收**:
  - QQQ / SPY / IWM / GLD / IAU / SLV 短卖成交数据完整
  - `available_at` 严格为 `observation_date + 1 营业日 + 14:00 ET`,NOT 当日、NOT 16:00 ET
  - T-12 专项 case 11 "FINRA T+1 防泄漏" 通过
  - 源语义警告(短卖成交量 ≠ short interest / total_volume ≠ 全市场)在 Metric Registry 与 Silver `quality_flags_json` 同步落库
  - **新增**:Evidence `semantic_caveat_zh` 含 "非全市场" 表述,LLM finding 的 `limitations_zh` 必含此条
  - **新增**:跨周末(W/F 五 → M 一)场景下 `max_staleness=2D` 走通,不出现 STALE 误报

#### T-06 · Silver 双时间表落地
- **阶段**:Phase 1 / 数据
- **责任**:`Coder`
- **依赖**:T-05
- **交付**:
  - `observations_bitemporal` 表(DuckDB)按 PRD §8.3 字段 + **新增字段集**:
    - `fill_type VARCHAR NOT NULL DEFAULT 'OBSERVED'`,枚举:**`OBSERVED | FORWARD_FILLED | CALENDAR_INFERRED | INTERPOLATED`**(4 值,不是 3 值)
      - `OBSERVED`:真实观测值
      - `FORWARD_FILLED`:前向填充(上一个 OBSERVED 值延续)
      - `CALENDAR_INFERRED`:日历推断值(如 `decision_clock=1605_ET` 时当日尚未收盘,标记为"推断")
      - `INTERPOLATED`:线性/样条插值
    - `fill_source_observation_id UUID`(当 `fill_type != OBSERVED` 时**必填**,指向被填充的源观测)
    - `fill_lag_days INTEGER`(填充延迟天数,用于 staleness 计算)
    - `vendor_symbol VARCHAR`(`source_metadata_json` 内必填,保留 `088691` / `GLD` / `VIXCLS` 等原始 vendor 标识)
  - Polars 解析器,每个 Adapter 一份
  - Pandera schema 校验(单位、主键、标的映射、时间因果、范围、`fill_type` 合法值)
  - **canonical_symbol 硬性规则(关键纪律 #8)**:`canonical_symbol` **必须**存在于 Instrument Registry,否则 Pandera 拒绝写入并报 `UNMAPPED_SYMBOL` 错误。原始 vendor symbol 保存在 `source_metadata_json.vendor_symbol` 中
  - **语义警告字段**:`source_semantic_warning` 同步从 Metric Registry 落 `quality_flags_json`(关键,后续 T-08 Feature 层会继承)
  - Append-only 写入:`data/silver/observations_bitemporal/source_name=<name>/dataset_name=<name>/available_date=YYYY-MM-DD/part-000.parquet`
- **验收**:
  - 同一 Raw 重跑产出 hash 一致的 Silver Parquet
  - 修订以新行追加,旧行 `valid_to` 标定
  - 解析器升级可从 Raw 回放,不依赖当前 API
  - **新增**:`fill_type` 4 枚举分别有 ≥1 条样例数据(单元测试覆盖)
  - **新增**:`fill_type != OBSERVED` 时 `fill_source_observation_id` 必填且指向真实观测行
  - **新增**:`fill_lag_days` 在 `forward_fill` 场景下与前次 OBSERVED 差值一致
  - **新增**:未在 Instrument Registry 的 symbol 写入 → 单元测试断言拒绝 + 报 `UNMAPPED_SYMBOL`
  - **新增**:源语义警告(FINRA short volume ≠ short interest / FINRA total_volume ≠ 全市场 / COT ≠ 实时资金流 / 13F ≠ 实时持仓)在 Silver `quality_flags_json` 完整落库,T-22 验证流水线可直接读取

#### T-07 · Availability Resolver
- **阶段**:Phase 1 / 数据
- **责任**:`Coder`
- **依赖**:T-03 / T-06
- **交付**:
  - `src/pit_market/normalization/availability.py`,`AvailabilityResolver.resolve()` 严格按 PRD §9.3 五级优先级:`官方发布时间 > 发布日历 > 保守规则 > 文件检测时间 > 抓取时间`
  - `config/availability_rules.yaml`:`cftc_friday_release` / `finra_regsho_t_plus_1` / `fred_realtime_period` / `13f_filing_acceptance` / `yfinance_close_final_1805_ET` / `yfinance_realtime_1605_ET` 等
  - 单元测试:5 级优先级各一例 + 缺省回落一例
- **验收**:
  - 同一观测不同源走不同路径,`available_at` 全部符合预期
  - 缺 `release_time` 时自动回落至发布日历
  - 缺发布日历时回落至配置保守规则

#### T-08 · Gold 基础特征
- **阶段**:Phase 1 / 数据
- **责任**:`Coder`
- **依赖**:T-06 / T-07
- **交付**:
  - `feature_observations_bitemporal` 表(DuckDB)按 PRD §8.4 + **`quality_flags_json` 继承 Silver 层的 `source_semantic_warning`**(关键纪律 #7)
  - 4 组特征:`price_features`(收益、波动、Z-score)/ `flow_features`(短卖占比、Z-score)/ `macro_features`(利差、分位数)/ `positioning_features`(managed_money_net 等)
  - **窗口配置化**:`window_configs` 写入 `config/metrics.yaml`,滚动窗口长度(如 63 日)、Z-score 窗口、分位数窗口等**不硬编码**,统一由 `FeatureConfig` 加载
  - **窗口长度进入 `configuration_hash`**:窗口变更 → 配置 hash 变更 → `feature_version` 自增
  - **期货展期检测(关键)**:针对 `GC=F` / `SI=F` 连续合约,调用 T-05a 暴露的 `detect_roll_events()` 接口获取展期事件列表;在特征计算时:
    - 展期日当日收益**设为 NaN**(不是展期价差)
    - `quality_flags_json` 标 `roll_adjusted: false`
    - Z-score 窗口内**排除**展期跳空点
    - 可选:实现 Panama 法 / 比率法展期调整价作为新特征 `field_name`(`GC=F.roll_adjusted_panama` / `GC=F.roll_adjusted_ratio`)
  - **多源分母同源(关键纪律 #8)**:计算 `flow__finra__short_ratio` 时,优先用同源 `total_volume`(分子分母均来自 FINRA),不得混入 SIP tape / NYSE 等其他源
  - 每条特征记录:`input_observation_ids_json` / `input_max_available_at` / `feature_definition_id` / `feature_version` / `configuration_hash`
- **验收**:
  - 特征重算生成新 `feature_version`,旧版本可读
  - `input_max_available_at` 严格不晚于决策时点
  - 同一输入+同一配置+同一版本 → 产出 hash 一致
  - **新增**:窗口长度修改 → `configuration_hash` 变更 → 旧特征不被静默覆盖
  - **新增**:`feature.quality_flags_json` 包含源语义警告(Silver 层传入),T-22 验证流水线读取时能找到
  - **新增**:T-22 验证流水线发现"某特征的 `quality_flags_json` 缺失其源语义的 `semantic_warning`" → 直接 REJECTED
  - **新增**:`GC=F` / `SI=F` 展期日当日收益为 NaN,`quality_flags_json.roll_adjusted=false`
  - **新增**:`short_ratio` 特征 100% 使用同源 `total_volume`,Evidence `semantic_caveat_zh` 标注"非全市场"

#### T-09 · PIT Panel Builder + Dagster 编排
- **阶段**:Phase 1 / 数据
- **责任**:`Coder`
- **依赖**:T-08
- **交付**:
  - `src/pit_market/pit/builder.py`:按 `decision_time` 重建,严格 `available_at <= decision_time AND valid_from <= decision_time AND (valid_to IS NULL OR valid_to > decision_time)`
  - 落盘:`data/gold/pit_panels/decision_date=YYYY-MM-DD/decision_clock=1805_ET/panel_version=v1/{market_panel.parquet,panel_lineage.parquet,quality_report.json,manifest.json}`
  - `pit_panel_registry` 表(PRD §8.5 字段)
  - Dagster 资产:`raw_yfinance_daily` / `raw_fred_alfred` / `raw_cftc_cot` / `raw_finra_regsho` → `normalized_observations_bitemporal` → 4 组 features → `pit_panel_daily`
  - 调度:每个交易日美东 18:05 ET 触发 + sensor 监听源文件 + partition + backfill 支持
- **验收**:
  - 给定 `decision_time=2026-07-20 18:05 ET`,产出 Panel
  - Panel hash 稳定;同输入+同配置+同版本重跑 → hash 一致
  - Dagster UI 可见资产依赖图;`pit backfill` 可指定日期范围回填

#### T-10 · FastAPI Panel/Slice 基础接口
- **阶段**:Phase 1 / API
- **责任**:`Coder`
- **依赖**:T-09
- **交付**:
  - `src/pit_market/api/main.py`:FastAPI 应用 + OpenAPI
  - 端点(PRD §15.1):
    - `GET /v1/panels/latest`
    - `GET /v1/panels/{panel_id}`
    - `POST /v1/panels/{panel_id}/slice`(最小版 SliceRequest:universe + fields)
    - `GET /v1/metrics/registry`
    - `GET /v1/instruments/registry`
  - 字段白名单:`metric_registry` 校验,拒绝未注册字段
  - PIT 因果服务侧再校验
- **验收**:
  - `GET /v1/panels/latest` 返回最新 panel 元信息
  - `POST /slice` 拒绝包含未注册字段的请求(400)
  - OpenAPI 文档自动生成

#### T-11 · 基础看板
- **阶段**:Phase 1 / 前端
- **责任**:`Coder`
- **依赖**:T-02 / T-10
- **交付**:
  - `/dashboard` 页面:默认加载 latest panel
  - 组件:`PITContextBar` / `KpiCard` / `PriceTimeSeries`(Plotly)/ `FieldsTable`(AG Grid,最小 4 列)
  - TanStack Query:`['panel', panelId]` / `['slice', panelId, requestHash]`
- **验收**:
  - 打开 `/dashboard` 1s 内看到 PIT Context Bar 和 KPI
  - Plotly 图表 hover 显示时间+值
  - 切换 panel 时 Header 同步更新 `panel_id / decision_time / quality`

#### T-12 · PIT 防泄漏自动测试(责任三角)
- **阶段**:Phase 1 / 验证
- **责任三角**(关键纪律 #3):
  - `Coder`:写测试框架(`tests/backend/test_pit_leakage.py` 主体)+ case 骨架
  - `General`:准备 fixture 数据(伪造 future-available 观测、修订前 vintage、跨源冲突、T+1 时序错位等)
  - `Verifier`:补充 **adversarial case**(故意构造拐角、批量注入、并发时序)+ 独立复跑
- **依赖**:T-05a / T-05b / T-05c / T-05d / T-09
- **交付**(PRD §19.1,**13 条 case**,从 9 条扩到 13 条):
  1. CFTC 周五前不可出现在 Panel
  2. 13F 仅在 filing acceptance time 后生效(用 SEC EDGAR `acceptancedatetime` 字段)
  3. ALFRED 修订前后应返回不同 vintage
  4. `available_at > decision_time` 必须被排除
  5. forward-fill 超过 `max_staleness` → `STALE` 或 `NaN`,且 `fill_type=FORWARD_FILLED` 必带 `fill_source_observation_id`
  6. 同输入+同配置+同版本重跑 → Panel hash 相同
  7. 解析器升级只能从 Raw 回放
  8. FINRA Reg SHO T+1:观察日 D 的数据,`available_at` 应严格 > D+1 16:00 ET,Panel 在 D+1 16:00 前不可见
  9. Yahoo Finance 收盘 vs 实时:`decision_clock=1605_ET` 不可见当日 close_final 价,`decision_clock=1805_ET` 不可见下一交易日数据
  10. **新增 — yfinance 拆股事件后 PIT**:`auto_adjust` 触发后,旧 `RAW_CLOSE` 行的 `valid_to` 被标定,Panel 重建仍可读到旧观测的 PIT 视图
  11. **新增 — FINRA Reg SHO T 日 18:05 Panel 不含 T 日数据**(覆盖 `t_plus_1_afternoon` 规则,严格 `<` T+1 14:00 ET)
  12. **新增 — ALFRED vintage vs FRED latest 差异**:同一序列在有修订的日期,ALFRED 必返回历史值,FRED 返回最新修订值;若两者相同 → Adapter 错调 FRED
  13. **新增 — 未注册 symbol 不得写入**:Pandera schema 拒绝未在 Instrument Registry 的 `canonical_symbol`,报 `UNMAPPED_SYMBOL`;Verifer 构造伪造 symbol 试图写入 Silver,断言拒绝
  14. **新增 — ETF shares 跨发行方误用**:GLD 用 BlackRock 规则会提前 ~18 小时引入 T+1 数据,Panel 应在 State Street 规则下严格不可见
- **验收**:
  - 14 条 case 全绿(原 9 + 新 5)
  - 任一 case 失败,`pytest` 立刻报错并定位测试名
  - Verifier 额外补充 ≥ 3 条 adversarial case(批量 / 并发 / 越界 / DST 切换周),单独跑通
  - 报告 `docs/phase-1-leakage-test.md` 记录每条 case 的 fixture 来源(Coder / General / Verifier)

#### T-13 · Phase 1 闸门
- **阶段**:Phase 1 / 验证
- **责任**:`Verifier`
- **依赖**:T-09 / T-10 / T-11 / T-12
- **交付**:`docs/phase-1-gate.md`
- **验收**:
  - T-12 全 14 条 case 绿(原 9 + 新 5;包含 Verifier 补充的 adversarial case)
  - 重建一致性:同决策时点同配置重跑 → Panel hash 一致
  - 解析器升级回放验证(人为改一版 parser,从 Raw 重放,字段映射正确)
  - 4 个 P0 Adapter 各自至少有 1 次"降级路径"演练(限流 / 错误 / 缺失 / T+1 时序)
  - API + 前端冒烟:可手动走通"打开 dashboard → 看到 KPI + 1 张图 + 1 张表"
  - Silver 表 `fill_type` 字段非空且 `fill_source_observation_id` 在 `fill_type != OBSERVED` 时必填

---

### Phase 2 — 动态切片与报告

#### T-14 · Slice API 完善 + SSE 进度流基础端点
- **阶段**:Phase 2 / API
- **责任**:`Coder`
- **依赖**:T-10
- **交付**:
  - 完整 `SliceRequest` 支持:universe / dateRange / domains / fields / sources / frequencies / states / quality / aggregation / sort / page
  - Pydantic v2 契约 + zod 前端对应类型
  - 服务端分页/排序/筛选(全部走 DuckDB 聚合)
  - **缓存方案(显式)**:Phase 2 使用 **in-process 内存缓存**(`cachetools.TTLCache`,LRU + TTL),**不引入 Redis**。缓存键:`SHA256(panel_id + normalized_slice_request + api_view_version + user_permission_scope)`,TTL 5–30 min
  - **SSE 进度流端点(基础版)**:为 PIT Panel 重建、ETL 跑批提供 `GET /v1/runs/{run_id}/stream`,事件格式同 PRD §14.3,5 阶段:`QUEUED → EVIDENCE_READY → LLM_RUNNING → VALIDATING → PUBLISHED`(Phase 2 此端点**仅用于 ETL/PIT**,不接入 LLM,LLM 部分由 T-23 扩展)
  - 事件 ID 必带,支持 `Last-Event-ID` 断点续传
  - 端点新增:`/v1/panels/replay` / `/v1/panels/{id}/export`(最小版,导出功能 T-18 扩展)
- **验收**:
  - 大表(>10k 行)服务端分页,前端不阻塞
  - 未注册字段 → 400;未授权权限 → 403
  - 同一 slice 重复请求命中内存缓存
  - **新增**:SSE 端点断线后根据 `Last-Event-ID` 续传成功
  - **新增**:Phase 5 迁移至 Redis 时,T-14 的 `cachetools` 接口与 T-31 的 `redis` 接口**抽象一致**(`CacheBackend` Protocol),迁移只换实现不改业务

#### T-15 · Filter Rail 完整版
- **阶段**:Phase 2 / 前端
- **责任**:`Coder`
- **依赖**:T-11
- **交付**:
  - 5 组筛选(PRD §13.2):Context / Universe / Data / Quality / Analysis
  - URL 参数同步:`?panel_id=...&symbols=...&domains=...&states=...&include_stale=false&range=...`
  - `SliceStore` 全局状态:Zustand + 单一 reducer
  - 预设保存/加载(watchlist 自定义 JSON,存 localStorage)
- **验收**:
  - 改变任一筛选,URL 即时同步
  - 复制 URL 到新标签页,切片状态完整恢复
  - 改变筛选,顶部 PIT Context Bar 同步显示

#### T-16 · 交叉过滤
- **阶段**:Phase 2 / 前端
- **责任**:`Coder`
- **依赖**:T-15
- **交付**:
  - 时间序列 brush → `dateRange` 同步
  - 热图 cell click → `selectedSymbols` / `selectedFields` 同步
  - 散点 lasso → `selectedSymbols` 同步
  - Finding 卡片 → `selectedEvidenceIds` 同步
  - Source Health 点击 → `selectedSources` 同步
  - Time Replay Slider → `decisionTime` 同步
  - 统一 dispatch 链路:`Plotly event → SliceStore action → TanStack Query 新 key → 局部刷新`
- **验收**:
  - 框选时间 → 热图/表/finding 同步刷新
  - 取消过期请求,旧响应不得覆盖新 slice

#### T-17 · 4 类报告模式
- **阶段**:Phase 2 / 前端
- **责任**:`Coder`
- **依赖**:T-16
- **交付**:
  - `/reports/[reportId]` 冻结报告模式:绑定固定 `panel_id / catalog_id / analysis_run_id`,不允许切换
  - `/dashboard` 动态研究模式:可切换 Panel/时间/标的
  - `/dashboard/replay?start=...&end=...` 历史回放:已物化直接读;按需 PIT 走 `ephemeral=true`(TTL 24h)
  - `/findings/[findingId]` 结论审计模式:固定 finding + 证据链
- **验收**:
  - frozen report 改 URL 试图替换 panel_id → 报 403 或被前端拒绝
  - 动态模式可"保存快照"将 ephemeral 固化为永久
  - 切换已物化 vs 按需 PIT,响应延迟差异符合预期

#### T-18 · 导出
- **阶段**:Phase 2 / 导出
- **责任**:`Coder`
- **依赖**:T-14 / T-17
- **交付**:
  - CSV / Parquet / PNG / SVG / HTML / PDF 导出
  - 导出 manifest:`{export_id, panel_id, slice_id, slice_request_sha256, data_response_sha256, report_version, created_at_utc}`
  - `/v1/panels/{id}/export` POST + 异步 job + 状态查询
- **验收**:
  - 每种格式均产出文件 + manifest
  - manifest 字段齐全,hash 一致
  - 权限检查:普通用户可 CSV/PNG,Parquet 受限(配置化)

#### T-19 · Phase 2 闸门
- **阶段**:Phase 2 / 验证
- **责任**:`Verifier`
- **依赖**:T-14 / T-15 / T-16 / T-17 / T-18
- **交付**:`docs/phase-2-gate.md`
- **验收**:
  - URL 参数可完整恢复可分享的切片状态
  - frozen report 不能通过 UI 改变底层 `panel_id`
  - **SSE 续传验证**(Phase 2 仅验证 ETL/PIT 流):断线后根据 `Last-Event-ID` 续传成功,不丢事件
  - tooltip 显示 `available_at` / quality / evidence_id
  - 请求取消/乱序时,旧响应不覆盖新 slice
  - 大表筛选/排序/翻页走服务端分页
  - **注**:LLM 分析流的完整 5 阶段验证(`VALIDATING` / `PUBLISHED` / 失败回滚)在 V-25 / T-23,不在此处

---

### Phase 3 — LLM 可追溯分析

#### T-20 · Evidence Catalog 构建
- **阶段**:Phase 3 / LLM
- **责任**:`Coder`
- **依赖**:T-09
- **交付**:
  - `src/pit_market/evidence/catalog.py`:从 panel 抽取 evidence_id 列表
  - 字段级血缘入口:`evidence_id → feature_observation_id → observation_id → raw_record_hash`
  - JSON Schema `evidence.schema.json` + catalog hash
  - 落盘:`data/metadata/evidence_catalogs/catalog_<id>.json` + `catalog_sha256`
  - 端点:`GET /v1/evidence/{evidence_id}` / `GET /v1/evidence/catalog/{catalog_id}`
- **验收**:
  - 同一 panel 多次抽取,evidence 列表稳定
  - 每个 evidence 字段血缘完整可达 raw

#### T-21 · LLM Adapter + JSON Schema 约束
- **阶段**:Phase 3 / LLM
- **责任**:`Coder`
- **依赖**:T-20
- **交付**:
  - `src/pit_market/llm/adapter.py`:统一接口 `analyze(catalog, prompt_template) -> Finding`
  - Provider 适配:`openai.py` / `gemini.py` / `local.py`
  - Prompt 模板走 `config/llm_prompts.yaml`,模板必须强制要求:
    - finding 含 `evidence_ids`(数组,至少 1 个)
    - `causal_language_level: ASSOCIATIVE_ONLY` 默认
    - `limitations_zh`(数组)
    - `llm_confidence` 与 `final_confidence` 分别报告
  - JSON Schema 强制:`llm_analysis.schema.json` + 输出校验
- **验收**:
  - 3 个 provider 至少 1 个跑通 mock 数据
  - 缺 `evidence_ids` 的 LLM 输出被 schema 拒绝
  - Prompt 模板版本可追溯(进入 `provenance`)

#### T-22 · LLM 验证流水线
- **阶段**:Phase 3 / LLM
- **责任**:`Coder`
- **依赖**:T-21
- **交付**:
  - 7 条规则(PRD §16.3)逐条实现:
    1. 每个 finding 至少 1 个 `evidence_id`
    2. 风险/方向 finding 默认 ≥ 2 个不同因子域证据
    3. `evidence_id` 必须存在于 Catalog
    4. 所有证据 `available_at <= decision_time`
    5. 质量非 VALID 的证据 → `final_confidence` cap
    6. 特殊源语义限制必须保留(FINRA≠short interest、COT≠实时资金流、13F≠实时持仓)
    7. schema/PIT/质量/证据校验失败 → REJECTED
  - 校验器:`src/pit_market/llm/validator.py`,返回结构化错误
- **验收**:
  - 7 条规则各有 1 个 case 触发并被正确拒绝/cap
  - REJECTED 的 finding 不得进入 `report` API

#### T-23 · SSE 分析流
- **阶段**:Phase 3 / 后端
- **责任**:`Coder`
- **依赖**:T-22
- **交付**:
  - 端点:`POST /v1/analyses` + `GET /v1/analyses/{id}` + `GET /v1/analyses/{id}/stream`
  - 5 阶段事件:`QUEUED → EVIDENCE_READY → LLM_RUNNING → VALIDATING → PUBLISHED`
  - 事件格式:`{event, id, data: {analysis_run_id, status, progress_pct, message_zh}}`
  - event ID 支持断点续传(Last-Event-ID)
  - 仅 `VALIDATED` 后才落正式 finding 到 report API
- **验收**:
  - 5 阶段事件按序触发
  - 校验失败的请求走 `analysis_rejected` 事件,不写报告
  - 客户端断开后重连,根据 `Last-Event-ID` 续传

#### T-24 · Finding 证据抽屉 + Lineage Drawer
- **阶段**:Phase 3 / 前端
- **责任**:`Coder`
- **依赖**:T-23
- **交付**:
  - `EvidenceDrawer` 组件:标题、结论、置信度、限制、evidence_id 列表(每项含当前值/状态/时间/质量/feature definition/source/查看原始血缘)
  - `LineageDrawer` 组件:Finding → Evidence → Feature → Observation → Raw 五级下钻,每节点元数据齐全
  - 路由:`/findings/[findingId]` 完整审计页
  - 端点:`GET /v1/findings/{id}` / `GET /v1/findings/{id}/lineage`
- **验收**:
  - 点击任一 finding → Drawer 打开且不离开当前研究上下文
  - 五级血缘逐级展开,Raw manifest URL 可点开
  - 节点元数据齐全(PRD §13.6 表格)

#### T-25 · Phase 3 闸门
- **阶段**:Phase 3 / 验证
- **责任**:`Verifier`
- **依赖**:T-20 / T-21 / T-22 / T-23 / T-24
- **交付**:`docs/phase-3-gate.md`
- **验收**:
  - finding 不得引用不存在的 `evidence_id`
  - 证据质量 STALE → `final_confidence` 自动 cap(具体阈值由 Verifier 独立测算)
  - finding 继承 FINRA/COT/13F 语义限制(`limitations_zh` 含相关条目)
  - 未通过 schema/PIT 验证的 finding 不可进入报告 API
  - 每个 finding 的 lineage endpoint 能查询至 Raw manifest
  - SSE 中断后根据 event ID 续传

---

### Phase 4 — 市场结构增强

#### T-26 · P1 数据源
- **阶段**:Phase 4 / 数据
- **责任**:`Coder`
- **依赖**:T-05(参考 P0 Adapter 模式)
- **交付**:
  - 4 个 P1 Adapter:`finra_otc.py` / `cboe_cfe.py` / `sec_edgar.py`(13F/13D/G/Form 4/8-K)/ `etf_shares.py`
  - 复用 Phase 1 Raw/Silver 模式 + 语义警告:`ATS 数据 ≠ 实时资金流`、`ETF shares outstanding ≠ 资金净流入`
  - **SEC EDGAR 关键**:`available_at` 严格使用 EDGAR filing 的 `acceptancedatetime` 字段(提交受理时间),**不**用 `periodOfReport`(报告期);两者可相差 45 天,用错字段会引入严重前视偏差
  - **ETF shares 按发行方配置(关键)**:不同发行方 `shares_outstanding` 更新节奏不同,各起独立 availability rule:
    ```yaml
    etf_shares_state_street:   # GLD / SLV
      release_offset_hours: 22     # T 日收盘后约 22 小时(T+1 10:00 ET)
      source: state_street_website
    etf_shares_blackrock:      # IAU
      release_offset_hours: 4      # T 日收盘后约 4 小时(T 日 20:00 ET)
      source: blackrock_website
    etf_shares_vanguard:       # 若有
      release_offset_hours: 18
      source: vanguard_website
    ```
  - **关键警告**:`shares_outstanding` 的变化本质上是 T 日的申赎流量,T+1 发布的值**不可**作为 T 日可知
  - 各源 `availability_rule_id` 写入 `availability_rules.yaml`
  - Raw `request.json` 必含 `ingested_at`(HTTP response 时间),用于审计
- **验收**:
  - 4 个 Adapter 各至少跑通 1 个标的
  - 语义警告在 Metric Registry 的 `semantic_warning` 字段中可见
  - **新增**:SEC 13F 的 `available_at` 等于 EDGAR `acceptancedatetime`(可在 T-12 防泄漏测试中复用 case 2)
  - **新增**:若 `acceptancedatetime` 缺失(罕见),回落至 `filing_date` + 配置保守规则 + 标 `quality_status = INFERRED_AVAILABILITY`
  - **新增**:GLD 走 `etf_shares_state_street`,Panel 在 T+1 10:00 ET 之前不得使用当日 shares_outstanding
  - **新增**:IAU 走 `etf_shares_blackrock`,Panel 在 T 日 20:00 ET 之前不得使用当日 shares_outstanding
  - **新增**:T-12 新增 case 14 — "ETF shares_outstanding 跨发行方误用:GLD 用 BlackRock 规则 → 提前 ~18 小时引入 T+1 数据"
- **完成**:✅ 2026-07-22 — 4 adapters 落地, 11 tests 绿;T-12 case 14 验证 18h 跨发行方泄漏

#### T-27 · Revision Timeline / Event Calendar / Source Health Matrix
- **阶段**:Phase 4 / 前端
- **责任**:`Coder`
- **依赖**:T-26
- **交付**:
  - `RevisionTimeline` 组件:宏观数据 vintage/修订对比(as-known-vs-latest toggle)
  - `EventCalendar` 组件:COT、宏观、SEC 发布事件,event click 关联图高亮
  - `SourceHealthMatrix` 组件:数据源 × 字段陈旧度
  - `DataHealthPanel` 仪表:源 SLA、新鲜度、错误、缺失率、质量检查
- **验收**:
  - 切换 as-known vs latest,数值与状态变化符合预期
  - 事件点击 → 关联图中事件点高亮
  - Source Health 至少 1 条陈旧数据时显式标红
- **完成**:✅ 2026-07-22 — `frontend/app/health/page.tsx` 落地 (Source Health Matrix + Revision Timeline via Plotly);npm build 9/9 routes OK

#### T-28 · OpenLineage 集成
- **阶段**:Phase 4 / 血缘
- **责任**:`Coder`
- **依赖**:T-09 / T-24
- **交付**:
  - Dagster OpenLineage 集成发出 dataset/run/field/finding facets
  - 自定义 Facet:`LLMProvenanceRunFacet.json`(模型、Prompt、Schema 版本、validation 结果)
  - `/lineage/[entityId]` 路由可视化:Finding → Evidence → Feature → Observation → Raw
  - 端点:`GET /v1/lineage/{entity_id}` 返回图数据
- **验收**:
  - 5 级血缘可视化完整,任一节点可点击查看元数据
  - OpenLineage 事件含 column lineage 与自定义 facet
- **完成**:✅ 2026-07-22 — `src/pit_market/api/lineage.py` 4 routes 落地, LLMProvenanceRunFacet JSON schema validated, 8 tests 绿

#### T-29 · Phase 4 闸门
- **阶段**:Phase 4 / 验证
- **责任**:`Verifier`
- **依赖**:T-26 / T-27 / T-28
- **交付**:`docs/phase-4-gate.md`
- **验收**:
  - 数据源失败/陈旧/推断发布时间均在 UI 显式呈现(不得静默隐藏)
  - 4 个 P1 数据源各自冒烟
  - 5 级血缘可视化可达,Raw manifest 可打开
- **完成**:✅ 2026-07-22 — `docs/phase-4-gate.md` 交付;274 tests / ruff / mypy / npm build 全绿;已知限制 (CFE / ETF 真实解析器) 已列入 Gate 报告"Known limitations"

---

### Phase 5 — 研究与生产化

#### T-30 · Walk-forward 回测 + 因子研究
- **阶段**:Phase 5 / 研究
- **责任**:`Coder` + `General`
- **依赖**:T-09
- **交付**:
  - `pit-market backfill` CLI:支持按 feature group / 日期范围 / `feature_version` 回填
  - `notebooks/walk_forward_*.ipynb`:Walk-forward 回测 + 因子 IC + 收益归因
  - 模型实验:XGBoost / 贝叶斯网络 / 状态模型
  - 回测结果落 `data/reports/backtests/`
- **验收**:
  - 给定 feature group + 日期范围,回填任务可启动
  - Walk-forward notebook 可端到端跑通
  - 回测结果导出 CSV + manifest
- **完成**:✅ 2026-07-22 — `src/pit_market/backtest/engine.py`(linear baseline + XGBoost pluggable);3 notebooks (`walk_forward_equity_v1` / `factor_ic_attribution_v1` / `bayesian_xgb_search_v1`);`pit-market backtest run` CLI;13 tests + 6 notebook tests 绿

#### T-31 · 生产化基础设施
- **阶段**:Phase 5 / 生产
- **责任**:`Coder`
- **依赖**:T-09
- **交付**:
  - **缓存迁移**(接 T-14):T-14 的 `cachetools.TTLCache` → Redis。**关键**:`CacheBackend` Protocol 已在 T-14 抽象,迁移只换实现不改业务代码。`docker-compose.yml` 加 Redis 服务
  - 对象存储 MinIO(Raw/Parquet)/ PostgreSQL(metadata 库)
  - `docker-compose.yml` 完整版:含所有服务
  - 鉴权(API Key 头)/ 权限矩阵(PRD §18)
  - 通知告警:数据源 SLA 异常 / 质量门禁失败 / 面板 STALE,对接 `lian-xin`(飞书)+ `ding-shi`(定时巡检)
- **验收**:
  - `docker compose up` 一键起整套
  - 通知可在飞书收到(测试群)
  - 权限矩阵按 PRD §18 严格执行
  - **新增**:缓存迁移后,同一 slice 的 `cachetools` 与 Redis 缓存命中率 + 一致性对比报告(允许误差 ≤ 1 个 TTL 边界)
  - **新增**:T-14 已有测试在 Redis 后端模式下全绿,证明 Protocol 抽象到位
- **完成**:✅ 2026-07-22 — `RedisCache` drop-in 兼容 `CacheBackend` Protocol(用 `set(..., ex=ttl)` 适配 redis 8.x 弃用 `setex`);`src/pit_market/auth/` API Key + 3 档权限矩阵(public/researcher/admin);Feishu webhook Notifier + 3 类告警(source_sla / quality_gate / panel_stale);`docker-compose.yml` 完整版(pit-api + dagster + redis + minio + postgres + bootstrap);hit-rate parity ≤ 1% 测试通过;38 tests 绿

#### T-32 · `pit-market` CLI 全套
- **阶段**:Phase 5 / 工程
- **责任**:`Coder`
- **依赖**:T-09 / T-22
- **交付**:
  - 命令(PRD §20):`init` / `refresh` / `pit build` / `pit replay` / `analyze` / `report build` / `export` / `healthcheck` / `backfill`
  - `pyproject.toml` 中 `[project.scripts]` 注册
  - `--help` 自描述
- **验收**:
  - 9 个命令均可 `--help` 看到自描述
  - `pit-market healthcheck` 报告 4 个 P0 源 SLA
  - `pit-market pit build --decision-time ...` 可重跑 Panel
- **完成**:✅ 2026-07-22 — `src/pit_market/cli.py` 10 commands:`init` / `refresh` / `pit build` / `pit replay` / `analyze` / `report build` / `export` / `healthcheck` / `backfill` / `backtest run`;每个 `--help` 自描述;`pyproject.toml` `[project.scripts]` 注册 `pit-market`;15 tests 绿

#### T-33 · 最终验收 — 对齐 PRD §22
- **阶段**:Phase 5 / 验收
- **责任**:`Verifier` + `Mavis`(判定)
- **依赖**:T-30 / T-31 / T-32
- **交付**:`docs/v1.1-acceptance.md`(逐条对应 PRD §22)
- **验收**(12 条,逐条打勾):
  1. `SPY/QQQ/GLD/SLV` 可自动生成可审计 PIT Panel
  2. COT/FRED-ALFRED/FINRA/SEC 按真实或保守 `available_at` 处理
  3. Raw/Silver/Feature/Panel/Evidence/Finding 均有版本+hash+lineage
  4. 回测与前端历史回放使用同一 PIT 查询逻辑
  5. Dashboard 支持标的/时间/领域/字段/数据源/质量状态/频率动态切片
  6. 图/表/KPI/finding/evidence 之间交叉过滤
  7. 每个图点/单元格可查数值/观察/可得时间/数据年龄/质量/来源/证据
  8. 每个 LLM finding 至少 1 个合法 evidence ID,血缘至 Raw manifest
  9. Frozen Report 可稳定复现;动态视图可另存为可审计快照
  10. SSE 展示 ETL/PIT replay/LLM 分析阶段,断线可恢复
  11. 大表走服务端分页,长时间序列走服务端聚合/下采样
  12. 数据源失败/陈旧/推断发布/LLM 验证失败均在 UI 显式呈现,不得静默隐藏
- **完成**:✅ 2026-07-22 — `docs/v1.1-acceptance.md` 12/12 全部对齐;346 tests / ruff / mypy / npm build 全绿

---

### Phase 6 — v2.0 数据与存储底座升级

> **对应 PRD v2.0**:Epic 1(真实历史数据接入)+ Epic 2(DuckDB 后端替换)
> **里程碑**:M1(数据真实化)+ M2(存储升级)
> **依赖关系**:M1 → M2(DuckDB 存真实数据);可与 Phase 7 的 M3(生产就绪)并行推进

#### T-34 · 真实历史数据适配器层
- **阶段**:Phase 6 / 数据(Epic 1 · F1.1)
- **责任**:`Coder`
- **依赖**:T-05a(复用 yfinance Adapter 模式)/ T-03(Instrument Registry)
- **交付**:
  - `src/pit_market/ingestion/adapters/base_adapter.py`:抽象接口 `fetch(symbol, start, end, freq) -> pl.DataFrame`
  - `src/pit_market/ingestion/adapters/yahoo_real_adapter.py`:yfinance wrapper,输出标准化 Parquet
    - 与 T-05a 现有 Adapter 区分:T-05a 用于 v1.1 manifest-only 流程,T-34 是 v2.0 真实数据管道
    - 支持 `freq` 参数:`1d / 1h / 1m`
    - 统一输出 schema:`{canonical_symbol, date, open, high, low, close, volume, adj_close, source}`
    - 限流处理:指数退避 + 1 req/s 上限,失败时 `quality_status = SOURCE_THROTTLED`
  - `src/pit_market/ingestion/adapters/polygon_adapter.py`:Polygon REST v2 历史聚合
    - 支持分钟/日线频率
    - 分页处理:`next_url` cursor 翻页
    - API key 通过 `.env` 的 `POLYGON_API_KEY` 注入,不得硬编码(纪律 #9)
  - 单元测试:每个 Adapter 至少 3 个 case(成功/限流/空数据)
- **验收**:
  - 两个 Adapter 输出 schema 一致,字段非空
  - 单 symbol 全量拉取(10 年日线)耗时 < 5s
  - 数据 schema 验证:空值率 < 0.1%,价格连续性检查(涨跌幅 > 50% 告警并标 `quality_flags_json.anomaly=true`)
  - Polygon 分页翻页正确处理,不丢数据
  - 重复请求得相同 hash,不入库(与 T-05a 一致的幂等性)
  - **PIT 兼容**:输出的 `available_at` 符合纪律 #8,精确到分钟,不破坏现有 T-12 防泄漏 case

#### T-35 · PIT 面板升级:manifest → real data
- **阶段**:Phase 6 / 数据(Epic 1 · F1.2)
- **责任**:`Coder`
- **依赖**:T-34 / T-09(PIT Builder)
- **交付**:
  - 升级 `src/pit_market/pit/builder.py`:`pit build` 执行时检测 `panel_type: real | manifest`
    - `manifest`:现有 v1.1 流程,仅元数据
    - `real`:调用 T-34 适配器拉取真实数据
  - 拉取结果以 Parquet 写入 `data/gold/pit_panels/{panel_id}/{asset_class}/{symbol}/raw/{freq}/YYYY-MM.parquet`(按月分区)
  - CLI 参数支持:`pit build --panel gold --source yahoo|polygon|auto`(auto = Yahoo 优先,失败降级 Polygon)
  - 降级路径:Yahoo 失败时自动切换 Polygon,`quality_report.json` 记录 `source_fallback: true`
  - 面板元数据新增 `panel_type` / `data_source` / `last_synced_at` 字段
- **验收**:
  - `pit build --panel gold --source yahoo` 生成包含真实收盘价的 Parquet
  - 前端 PIT 面板页可展示真实时间序列图(接 T-11 dashboard)
  - `--source auto` 模式下 Yahoo 失败自动降级 Polygon,不报错
  - 同输入+同配置重跑 → Panel hash 一致(与 T-09 验收标准一致)
  - manifest 模式仍可用(向后兼容 v1.1 流程)

#### T-36 · 增量更新调度
- **阶段**:Phase 6 / 数据(Epic 1 · F1.3)
- **责任**:`Coder`
- **依赖**:T-37(DuckDB data_registry 表,必须先完成建表)/ T-35
- **交付**:
  - CLI 命令:`pit sync --symbol GC=F --since 2025-01-01`(同时在 T-48 前端“数据管理”页触发)
  - 记录每个 symbol 的 `last_fetched_at` 到 DuckDB `data_registry` 表(T-37 建表)
  - 支持 dry-run 模式:`--dry-run` 打印待下载范围,不实际写盘
  - 增量逻辑:仅拉取 `last_fetched_at` 之后的数据,避免全量重复下载
  - `pyproject.toml` 中 `[project.scripts]` 注册 `pit sync` 子命令
  - 结构化日志(`structlog`):`job_id` / `symbol` / `date_range` / `duration_ms`(纪律 #10)
- **验收**:
  - `pit sync --symbol SPY --since 2025-01-01` 仅拉取增量数据
  - `--dry-run` 打印待拉取范围,不写盘
  - `data_registry` 表正确记录 `last_fetched_at`
  - 重复 sync 幂等,已拉取的数据不重复写入
  - `pit sync --help` 自描述

#### T-37 · DuckDB 存储层
- **阶段**:Phase 6 / 存储(Epic 2 · F2.1)
- **责任**:`Coder`
- **依赖**:T-01(项目骨架)
- **交付**:
  - `src/pit_market/storage/duckdb_engine.py`:单例连接管理,db 路径从 `.env` 的 `PIT_DUCKDB_PATH` 读取
  - `src/pit_market/storage/panel_store.py`:封装 CRUD:`upsert_panel()` / `query_panel()` / `list_panels()` / `delete_panel()`
  - `src/pit_market/storage/migrations/001_init_schema.sql`:建表 DDL
    - `panels`(panel_id, panel_type, asset_class, symbols, source, created_at, updated_at, panel_hash, manifest_json)
    - `data_registry`(symbol, source, freq, last_fetched_at, row_count, quality_flags_json)
    - `replay_snapshots`(snapshot_id, panel_id, as_of_date, created_at, snapshot_hash)
    - `backtest_runs`(run_id, strategy, panel_id, params_json, result_json, created_at, status)
  - `src/pit_market/storage/backend.py`:`StorageBackend` Protocol 定义(纪律 #9),包含 `query()` / `upsert()` / `list()` / `delete()` 抽象方法
  - `PIT_STORAGE_BACKEND=duckdb|polars` 环境变量切换(小数据集本地开发仍可用 Polars)
  - DuckDB 直接查询 Parquet 目录:`SELECT * FROM read_parquet('data/gold/**/*.parquet')`
  - 保留 Polars 作为计算层(DuckDB → Arrow → Polars 零拷贝)
- **验收**:
  - `PIT_STORAGE_BACKEND=duckdb pytest tests/backend/test_storage/` 全部通过
  - `StorageBackend` Protocol 抽象正确,Polars 和 DuckDB 两个实现可互换
  - 4 张表的 DDL 正确执行,CRUD 操作正常
  - `.env` 缺 `PIT_DUCKDB_PATH` 时回落到默认路径 `data/pit.duckdb`
  - **并发写入压力测试**:2 进程同时执行 `upsert_panel()` 不报 `database is locked` 错误;写入路径统一收敛到单进程 worker(通过 `duckdb_engine.py` 内置 `threading.Lock` 或进程级文件锁实现)

#### T-38 · API 层 DuckDB 适配
- **阶段**:Phase 6 / API(Epic 2 · F2.2)
- **责任**:`Coder`
- **依赖**:T-37 / T-10(FastAPI 基础)
- **交付**:
  - FastAPI 路由中所有 `build_panel()` 调用替换为 `panel_store.query_panel()`(走 `StorageBackend` Protocol)
  - 新增端点 `POST /api/v1/sql`(仅开发模式启用,纪律 #9):
    - 接受 read-only DuckDB SQL,返回 JSON
    - 查询超时限制:30s
    - 结果集上限:10,000 行
    - `ENV != development` 时返回 403
  - 现有端点响应格式不变(向后兼容 v1.1 API 契约)
  - 新增端点 `GET /api/v1/registry/search?q=`(Symbol 模糊搜索,供 T-51 前端注册表页调用)
- **验收**:
  - 现有 API 响应格式与 v1.1 完全一致(向后兼容)
  - `POST /api/v1/sql` 在开发模式下执行只读 SQL 返回 JSON
  - `POST /api/v1/sql` 在生产模式(`ENV=production`)返回 403
  - SQL 查询超时 30s 后自动取消
  - 结果集超过 10,000 行时截断 + 警告

#### T-39 · 性能基准验证
- **阶段**:Phase 6 / 存储(Epic 2 · F2.3)
- **责任**:`Coder` + `Verifier`
- **依赖**:T-37 / T-38
- **交付**:
  - `tests/backend/test_perf_baseline.py`:性能基准测试套件
  - 测试数据生成器:使用 `numpy.random` 生成确定性模拟数据(seed=42,可复现),模拟 500 / 1000 symbols × 5 年日线数据;**禁止**使用 Faker 等随机库,确保 Coder 与 General 生成结果一致
  - 性能对比报告:Polars in-memory vs DuckDB,输出到 `docs/phase-6-perf-report.md`
  - 基准指标:
    | 场景 | Polars in-memory(现状) | DuckDB 目标 |
    |:--|:--|:--|
    | 500 symbols 全量加载 | OOM / >30s | < 3s |
    | 单因子横截面计算(500×2520行) | ~2s | < 1s |
    | 历史 replay 快照生成 | ~5s | < 2s |
- **验收**:
  - 1000 symbols 日线 5 年数据加载内存占用 < 500 MB
  - 3 个场景全部达到 DuckDB 目标值
  - `PIT_STORAGE_BACKEND=duckdb pytest tests/backend/test_perf_baseline.py` 全绿
  - 现有 API 响应格式不变(向后兼容)
- **完成**:✅ 2026-07-23 — `tests/backend/test_perf_baseline.py` 9/9 tests passed; DuckDB 全场景达标; 1000 symbols 18.8 MB < 500 MB

#### T-40 · Phase 6 闸门
- **阶段**:Phase 6 / 验证
- **责任**:`Verifier`
- **依赖**:T-34 / T-35 / T-36 / T-37 / T-38 / T-39
- **交付**:`docs/phase-6-gate.md`
- **验收**:
  - `pit build --panel gold --source yahoo` 生成包含真实收盘价的 Parquet,前端 dashboard 可展示时间序列图
  - DuckDB 存储层性能达标:500 symbols < 3s,1000 symbols 内存 < 500 MB
  - 增量更新 `pit sync` 幂等,dry-run 不写盘
  - 现有 T-12 PIT 防泄漏测试 14 条 case 全绿(回归验证)
  - `PIT_STORAGE_BACKEND=polars` 模式下所有测试仍通过(向后兼容)
  - `/api/v1/sql` 端点生产模式下返回 403(安全隔离)
  - Polygon API key 未硬编码(代码审计)
  - `ruff check` + `mypy src` + `pnpm build` 全绿
- **完成**:✅ 2026-07-23 — `docs/phase-6-gate.md` 交付; 374 tests / ruff / npm build 全绿; `/api/v1/sql` 403 verified

#### T-40b · Phase 6 DuckDB 性能独立复现
- **阶段**:Phase 6 / 验证
- **责任**:`Verifier`
- **依赖**:T-39(Coder 性能基准)
- **交付**:Verifier 独立脚本 `/tmp/perf_independent.sh` + 复现报告
- **验收**:
  - Verifier 用**独立脚本**(不复用 Coder 的 `test_perf_baseline.py`)在 `/tmp` 下生成测试数据并运行 DuckDB 性能基准
  - 3 个场景(500 symbols 全量加载 / 单因子横截面 / replay 快照)独立复现结果与 T-39 偏差 ≤ 10%
  - 若偏差 > 10%,Verifier 报告具体差异数据并阻断闸门
  - 独立验证 `PIT_STORAGE_BACKEND=polars` 模式回退正确(不报错,结果一致)
  - 独立验证 2 进程并发 `upsert` 不报锁冲突(T-37 并发写入要求)
- **完成**:✅ 2026-07-23 — `scripts/perf_independent.py` 全场景 PASS; S1 <1ms / S2 0.2s / S3 <1ms / MEM 18.8MB; Polars backend 切换 PASS

#### T-40c · Phase 6 最终闸门
- **阶段**:Phase 6 / 验证
- **责任**:`Verifier`
- **依赖**:T-40 / T-40b
- **交付**:`docs/phase-6-gate.md` 最终签署(合并 T-40 + T-40b 证据)
- **验收**:
  - T-40 全部验收项 PASS
  - T-40b 独立性能复现偏差 ≤ 10%
  - 两项证据合并后签署最终闸门
- **完成**:✅ 2026-07-23 — T-40 + T-40b 证据合并,Phase 6 最终闸门 PASS

---

### Phase 7 — v2.0 生产化与前端全功能演进

> **对应 PRD v2.0**:Epic 3(本地 CI/CD 生产模式验证)+ Epic 4(OpenAPI 文档扩展)+ Epic 5(CLI→前端 UI 全功能迁移)
> **里程碑**:M3(生产就绪)+ M4(UI 完整)
> **依赖关系**:M3 可与 M1/M2 并行推进;M4 依赖 Phase 6 的真实数据和 DuckDB 存储层

#### T-41 · 本地 CI 脚本 + 冒烟测试
- **阶段**:Phase 7 / 工程(Epic 3 · F3.1 + F3.2)
- **责任**:`General`
- **依赖**:T-31(docker-compose.yml 完整版)
- **交付**:
  - `scripts/ci-local.sh`:主流水线脚本,执行顺序:
    1. `docker compose build --no-cache` — 全量构建镜像
    2. `docker compose run --rm api pytest tests/ -x -q` — Python 测试
    3. `docker compose run --rm frontend npm run build` — Next.js prod build
    4. `docker compose up -d` — 启动所有服务
    5. `bash scripts/smoke-test.sh` — 端到端冒烟测试
    6. `docker compose down` — 清理
  - `scripts/smoke-test.sh`:生产模式冒烟测试(curl + jq):
    - `curl -f http://localhost:8000/health` — API 健康检查
    - `curl -f http://localhost:8000/api/v1/panels` — PIT 面板列表
    - `curl -f http://localhost:3000` — 前端 prod 页面可达
    - `curl -f http://localhost:8000/docs` — OpenAPI Swagger UI 可达
    - `curl -f http://localhost:8000/openapi.json` — OpenAPI schema 可达
    - 所有 curl 返回 HTTP 200,失败则打印响应体并退出码 1
  - 本地优先:不引入 GitHub Actions 依赖(PRD v2.0 非功能需求)
- **验收**:
  - `bash scripts/ci-local.sh` 在干净环境从零执行完整通过
  - 冒烟测试所有 curl 返回 HTTP 200
  - 脚本失败时输出清晰的错误信息和失败步骤名
  - 脚本在 Windows PowerShell 和 Linux bash 下均可执行(或提供对应版本)

#### T-42 · Git Pre-commit Hook
- **阶段**:Phase 7 / 工程(Epic 3 · F3.3)
- **责任**:`General`
- **依赖**:T-41
- **交付**:
  - `scripts/pre-commit-check.sh`:快速检查(< 60s):
    - `ruff check src/` — Python lint
    - `mypy src/pit_market/ --ignore-missing-imports` — 类型检查
    - `cd frontend && npm run lint` — ESLint
    - `pytest tests/backend/ -x -q --timeout=30` — 仅跑单元测试
  - 安装方式:`ln -s ../../scripts/pre-commit-check.sh .git/hooks/pre-commit`(或 Windows 下等效操作)
  - 失败时阻止提交,输出具体失败的检查项和错误信息
- **验收**:
  - `git commit` 时自动触发,失败时阻止提交
  - 全套检查在 60s 内完成
  - 手动执行 `bash scripts/pre-commit-check.sh` 也可独立运行

#### T-43 · OpenAPI 路由注解增强
- **阶段**:Phase 7 / API(Epic 4 · F4.1)
- **责任**:`Coder`
- **依赖**:T-10(FastAPI 基础)/ T-38(DuckDB API 适配)
- **交付**:
  - 为所有 FastAPI 路由添加:
    - `summary` / `description` / `tags`
    - `response_model` 明确指定 Pydantic schema
    - `responses` 字典覆盖 400/404/422/500 错误码及示例 body
  - 涉及文件:`src/pit_market/api/main.py` / `src/pit_market/api/panels.py` / `src/pit_market/api/slice.py` / `src/pit_market/api/lineage.py` / `src/pit_market/api/evidence.py`
  - 示例:
    ```python
    @router.post(
        "/panels/build",
        summary="构建 PIT 面板",
        description="触发 PIT 面板构建任务,支持实时 SSE 进度推送",
        tags=["panels"],
        response_model=BuildResponse,
        responses={
            422: {"description": "参数校验失败", "model": ErrorDetail},
            503: {"description": "数据源不可达"},
        }
    )
    ```
  - 统一错误响应模型 `ErrorDetail`(含 `error_code` / `message` / `details`)
- **验收**:
  - Swagger UI 所有端点有 summary + 至少一个响应示例
  - 每个端点的 400/404/422/500 错误码均有示例 body
  - `GET /openapi.json` 输出完整,可导入 Postman/Insomnia

#### T-44 · README curl 示例扩展
- **阶段**:Phase 7 / 文档(Epic 4 · F4.2)
- **责任**:`General`
- **依赖**:T-43
- **交付**:
  - 在 PRD 文档的 `## API Quick Reference` 章节补充以下 curl 示例:
    | 操作 | curl 命令 |
    |:--|:--|
    | 健康检查 | `curl http://localhost:8000/health` |
    | 列出所有面板 | `curl http://localhost:8000/api/v1/panels` |
    | 构建面板 | `curl -X POST .../panels/build -d '{"asset":"gold","source":"yahoo"}'` |
    | 触发 replay | `curl -X POST .../replay -d '{"panel_id":"...","as_of":"2024-01-15"}'` |
    | 生成报告 | `curl -X POST .../report/build -d '{"panel_id":"...","format":"pdf"}'` |
    | 跑回测 | `curl -X POST .../backtest/run -d '{"strategy":"momentum","panel_id":"..."}'` |
    | 数据导出 | `curl http://localhost:8000/api/v1/export/csv?panel_id=...` |
  - 7 类操作全覆盖,每个 curl 均可复制粘贴执行
- **验收**:
  - 7 类 curl 示例覆盖全部操作类型
  - 在本地 `docker compose up` 后,每个 curl 均可复制粘贴执行并返回预期结果

**完成**: ✅ 2026-07-23 — 在 PRD v2.0 中添加 `### API Quick Reference` 章节，13 类 curl 示例覆盖全部操作类型

#### T-45 · 独立 API 文档站
- **阶段**:Phase 7 / 文档(Epic 4 · F4.3)
- **责任**:`Coder`
- **依赖**:T-43
- **交付**:
  - `docs/api/` 目录:生成静态 OpenAPI HTML(使用 `redocly build-docs` 或等效工具)
  - CLI 命令:`pit docs serve` 在本地 `localhost:8080` 启动文档站
  - `pyproject.toml` 中 `[project.scripts]` 注册 `pit docs serve`
  - 文档站包含:所有端点描述、请求/响应 schema、示例代码、错误码说明
- **验收**:
  - `pit docs serve` 可在本地访问完整 Redoc 站
  - 文档站内容与 Swagger UI 一致
  - `pit docs serve --help` 自描述

**完成**: ✅ 2026-07-23 — `pit docs serve` + `pit docs build` 子命令已实现，Redoc 静态 HTML 生成至 docs/api/index.html

#### T-46 · 后端 API 扩展(供前端 UI 调用)
- **阶段**:Phase 7 / API(Epic 5 前置)
- **责任**:`Coder`
- **依赖**:T-37 / T-38
- **交付**:
  - 新增/升级以下端点(供 T-48~T-53 前端页面调用):
    - `POST /api/v1/panels/build` + SSE 流 `/api/v1/panels/build/stream` — 面板构建(供 T-48)
    - `GET /api/v1/panels/{id}/snapshots` — 历史快照列表(供 T-49)
    - `GET /api/v1/panels/{id}/snapshots/{date}` — 指定日期快照(供 T-49)
    - `POST /api/v1/report/build` — 报告生成,支持 `format=md|pdf`(供 T-50)
    - `GET /api/v1/reports` — 报告历史列表(供 T-50)
    - `POST /api/v1/backtest/run` — 回测提交(供 T-51)
    - `GET /api/v1/backtest/{job_id}` — 回测状态查询(供 T-51)
    - `GET /api/v1/backtest/{job_id}/results` — 回测结果详情(供 T-51)
    - `GET /api/v1/registry/search?q=` — Symbol 模糊搜索(供 T-51,已在 T-38 落地)
    - `GET /api/v1/export/csv` / `GET /api/v1/export/parquet` — 数据导出(供 T-51)
    - `GET /api/v1/system/health` — 系统健康详情(供 T-53)
    - `GET /api/v1/system/tasks` — 异步任务队列(供 T-53)
    - `POST /api/v1/system/tasks/{id}/cancel` — 取消任务(供 T-53)
    - `POST /api/v1/sync` — 数据同步触发(供 T-48 数据管理页)
  - 所有端点走 `StorageBackend` Protocol(纪律 #9)
  - 异步任务状态通过 `structlog` 记录 `job_id` / `symbol` / `duration_ms`(纪律 #10)
- **验收**:
  - 所有新端点在 Swagger UI 可见且有 summary
  - SSE 流 `/api/v1/panels/build/stream` 可连接并接收进度事件
  - 异步任务(报告生成/回测)可通过 `job_id` 查询状态
  - 所有端点响应格式与 v1.1 向后兼容

#### T-47 · 前端依赖升级与公共组件
- **阶段**:Phase 7 / 前端(Epic 5 前置)
- **责任**:`Coder`
- **依赖**:T-02(前端骨架)/ T-46(后端 API 就绪)
- **交付**:
  - 新增前端依赖:
    - `recharts`(图表,替代/补充 Plotly)
    - `react-hook-form` + `zod`(表单校验)
    - `react-markdown` + `remark-gfm`(Markdown 预览)
    - `@radix-ui/react-slider`(时间轴滑块)
  - 新增/升级公共组件:
    - `components/SSEProgressBar.tsx`:SSE 进度条组件(升级现有,支持 EventSource 订阅)
    - `components/Toast.tsx`:全局 toast 通知(成功/错误/警告)
    - `lib/useSSEStream.ts`:SSE hook,封装 EventSource 连接/重连/错误处理
    - `lib/queryKeys.ts`:TanStack Query key 常量(新增 panels/build/reports/backtest/registry/system)
    - `types/api.ts`:扩展类型定义(对齐 T-46 新增端点)
  - 全局 layout 新增侧边导航栏:面板管理 / 历史 Replay / 报告生成 / 回测工作台 / 注册表 / 系统
- **验收**:
  - `pnpm build` 零 error,warning < 10 条
  - `pnpm lint` + `tsc --noEmit` 通过
  - 侧边导航栏可点击跳转 6 个页面
  - SSE hook 可连接后端 SSE 端点并接收事件

#### T-48 · 面板管理页(对应 `pit build`)
- **阶段**:Phase 7 / 前端(Epic 5 · F5.1)
- **责任**:`Coder`
- **依赖**:T-47 / T-46(面板构建 API + SSE)
- **交付**:
  - 路由:`/panels`(面板列表 + 创建)
  - `frontend/app/panels/page.tsx`:面板管理页
  - 表单字段:asset class、symbol list(多选 + 自定义输入)、数据源(Yahoo/Polygon)、时间范围、频率
  - 点击“构建”后通过 `EventSource` 订阅 `/api/v1/panels/build/stream`,实时展示进度条 + 日志
  - 面板列表支持:排序、过滤(按状态/资产类)、一键删除/重建
  - 数据管理子页:`pit sync` 触发按钮 + 增量更新状态显示(对接 T-36)
  - 所有表单提交有 loading 状态 + 错误提示(toast 通知)
- **验收**:
  - `pit build` 能做的事,通过面板管理页 UI 操作完全等价(纪律 #10)
  - SSE 进度条实时更新,断线后自动重连
  - 面板列表可排序/过滤/删除/重建
  - 表单提交有 loading 状态,失败时 toast 提示

#### T-49 · 历史 Replay 页(对应 `pit replay`)
- **阶段**:Phase 7 / 前端(Epic 5 · F5.2)
- **责任**:`Coder`
- **依赖**:T-47 / T-46(快照 API)
- **交付**:
  - 路由:`/replay`
  - `frontend/app/replay/page.tsx`:历史 Replay 页
  - 时间轴滑块(日级粒度,范围选择,使用 `@radix-ui/react-slider`)
  - 左右双面板对比:选择两个历史时刻的面板快照
  - 变化高亮:相对于基准日期的因子值变化(红/绿色)
  - 导出当前快照为 CSV
  - 对接 `GET /api/v1/panels/{id}/snapshots` 和 `GET /api/v1/panels/{id}/snapshots/{date}`
- **验收**:
  - 时间轴滑块可拖拽选择日期,面板数据实时更新
  - 双面板对比模式可正确显示两个时刻的差异
  - 变化高亮颜色正确(正值绿色/负值红色)
  - CSV 导出文件内容与页面显示一致

#### T-50 · 报告生成页(对应 `pit report build`)
- **阶段**:Phase 7 / 前端(Epic 5 · F5.3)
- **责任**:`Coder`
- **依赖**:T-47 / T-46(报告生成 API)
- **交付**:
  - 路由:`/reports/new`(新建报告)和 `/reports`(报告历史)
  - `frontend/app/reports/new/page.tsx`:报告配置 + 预览
  - 支持模板选择:`summary | detailed | custom`
  - 实时 Markdown 预览(右侧面板,`react-markdown` + `remark-gfm` 渲染)
  - “生成 PDF” 按钮调用后端 `/api/v1/report/build?format=pdf`,触发浏览器下载
  - 报告历史列表:列出已生成报告,支持重新下载
  - 对接 `POST /api/v1/report/build` 和 `GET /api/v1/reports`
- **验收**:
  - 模板切换后预览内容实时更新
  - Markdown 渲染正确(表格、列表、标题、代码块)
  - PDF 下载触发浏览器下载对话框
  - 报告历史列表可重新下载

#### T-51 · 回测工作台(对应 `pit backtest run`)
- **阶段**:Phase 7 / 前端(Epic 5 · F5.4)
- **责任**:`Coder`
- **依赖**:T-47 / T-46(回测 API)
- **交付**:
  - 路由:`/backtest`
  - `frontend/app/backtest/page.tsx`:回测工作台
  - 策略配置表单:策略类型(动量/均值回归/自定义)、参数面板(lookback window、rebalance freq 等)
  - 提交后异步执行,任务状态通过轮询 `/api/v1/backtest/{job_id}` 跟踪(SWR `refreshInterval: 2000`)
  - 结果展示:
    - 累计收益曲线(Recharts 折线图)
    - 年化 Sharpe、最大回撤、胜率 KPI 卡片
    - 持仓权重热力图
  - 多次回测结果可叠加对比
  - 对接 `POST /api/v1/backtest/run` / `GET /api/v1/backtest/{job_id}` / `GET /api/v1/backtest/{job_id}/results`
- **验收**:
  - 回测结果图表在 Chrome/Firefox 渲染正常
  - 多次回测可叠加对比,曲线颜色区分
  - KPI 卡片数值与后端返回一致
  - 异步任务状态轮询正常,完成后自动停止

#### T-52 · 注册表 & 数据导出页(对应 `pit registry query` / `pit export`)
- **阶段**:Phase 7 / 前端(Epic 5 · F5.5)
- **责任**:`Coder`
- **依赖**:T-47 / T-46(注册表搜索 + 导出 API)
- **交付**:
  - 路由:`/registry`
  - `frontend/app/registry/page.tsx`:注册表 & 数据导出
  - Symbol 搜索框(支持模糊匹配,调用 `/api/v1/registry/search?q=`)
  - 面板元数据详情面板(schema、行数、时间范围、数据源、last_fetched_at)
  - 导出按钮:CSV(直接下载)/ Parquet(后端打包后下载)
  - 对接 `GET /api/v1/registry/search` / `GET /api/v1/export/csv` / `GET /api/v1/export/parquet`
- **验收**:
  - Symbol 搜索模糊匹配正确,结果实时更新
  - 元数据详情显示完整(包含 DuckDB `data_registry` 表的字段)
  - CSV/Parquet 导出触发浏览器下载,文件内容正确

#### T-53 · 系统健康页(对应 `pit health`)
- **阶段**:Phase 7 / 前端(Epic 5 · F5.6)
- **责任**:`Coder`
- **依赖**:T-47 / T-46(系统健康 API)
- **交付**:
  - 路由:`/system`(替代或增强现有 `/health`)
  - `frontend/app/system/page.tsx`:系统健康页
  - 实时健康卡片:API、DuckDB、数据源连通性(Yahoo/Polygon ping)
  - 任务队列:当前运行/排队/失败的异步任务列表,支持手动取消
  - 环境信息:版本号、Python/Node 版本、`PIT_STORAGE_BACKEND` 当前值
  - 对接 `GET /api/v1/system/health` / `GET /api/v1/system/tasks` / `POST /api/v1/system/tasks/{id}/cancel`
- **验收**:
  - 健康卡片实时更新(轮询间隔 5s)
  - 任务队列显示正确,取消按钮可用
  - 环境信息与 `docker compose` 实际配置一致
  - 数据源连通性 ping 结果显示正确

#### T-54 · Phase 7 闸门
- **阶段**:Phase 7 / 验证
- **责任**:`Verifier`
- **依赖**:T-41 / T-42 / T-43 / T-44 / T-45 / T-46 / T-47 / T-48 / T-49 / T-50 / T-51 / T-52 / T-53
- **交付**:`docs/phase-7-gate.md`
- **验收**:
  - `bash scripts/ci-local.sh` 在干净环境从零执行完整通过
  - pre-commit hook 在 `git commit` 时自动触发,失败时阻止提交
  - Swagger UI 所有端点有 summary + 至少一个响应示例
  - README curl 示例 7 类操作均可复制粘贴执行
  - `pit docs serve` 可在本地访问完整 Redoc 站
  - 前端所有 6 个主页面功能完整,无“施工中”占位符
  - `pit build` 能做的事,通过面板管理页 UI 操作完全等价
  - 回测结果图表在 Chrome/Firefox 渲染正常
  - 所有表单提交有 loading 状态 + 错误提示(toast 通知)
  - 前端 prod build(`npm run build`)零 error,warning < 10 条
  - CLI 所有子命令仍可用(向后兼容,v2 未删除任何 CLI 子命令)
  - `/api/v1/sql` 生产模式返回 403
  - `ruff check` + `mypy src` + `pnpm build` + `pnpm lint` 全绿
  - T-12 PIT 防泄漏测试 14 条 case 全绿(回归验证)

**完成**: ✅ 2026-07-23 — 15/15 验收项全 PASS；backend 388 tests、PIT 14 cases、frontend 0 errors/3 warnings、ruff 全绿

---

## 3. 跨阶段横切关注

| 主题 | 阶段 | TODO | 备注 |
|:--|:--|:--|:--|
| Trading Calendar | Phase 0 起 | T-03b / T-07 / T-09 / T-12 | NYSE/Nasdaq 交易日历是上游资产,所有 PIT 推算前先过日历;非交易日 `available_at` 推算错误 = 前视偏差 |
| Silver `fill_type` 字段 | Phase 1 起 | T-06 / T-08 / T-12 | `OBSERVED \| FORWARD_FILLED \| CALENDAR_INFERRED \| INTERPOLATED`(4 枚举,与 T-06 交付一致)+ `fill_source_observation_id` 必填(`fill_type != OBSERVED` 时),区分观测值与推算值;Feature / Evidence / Finding 全链路读取 |
| 语义警告传播链 | Phase 1 起 | T-05a~d / T-06 / T-08 / T-20 / T-21 | Source → Silver `quality_flags_json` → Feature `quality_flags_json` → Evidence `semantic_caveat_zh` → LLM `limitations_zh`;任意一层丢失 → Verifier FAIL |
| PIT 字段精度 | Phase 1 起 | T-05a~d / T-06 | `available_at` 必须 `TIMESTAMPTZ` 精确到分钟;CFTC 15:30 ET、FINRA 14:00 ET、ETF 按发行方 offset 都按分钟级 |
| API 路由硬性规则 | Phase 1 起 | T-05b / T-06 | FRED 必走 ALFRED;canonical_symbol 必注册;vendor symbol 必存 `source_metadata_json` |
| 期货展期处理 | Phase 1 | T-05a / T-08 | T-05a 暴露 `detect_roll_events()` 接口;T-08 特征层消费,展期日收益 NaN,Z-score 窗口排除跳空 |
| 缓存抽象(`CacheBackend` Protocol) | Phase 2 起 → Phase 5 | T-14 / T-31 | Phase 2 用 `cachetools` in-process;Phase 5 迁 Redis。**接口一致**保证迁移只换实现 |
| SSE 进度流 | Phase 2 起 → Phase 3 | T-14 / T-23 | T-14 落地基础 SSE 端点(ETL/PIT 流);T-23 扩展为 LLM 5 阶段;所有 SSE 端点带 event ID,支持 `Last-Event-ID` 续传 |
| 性能与缓存 | Phase 2 起 | T-14 / T-16 / T-18 | 5 年日频图服务端下采样至 1k–2k 点;TanStack Query 30–120s;Redis 5–30min;物化 Panel 永久 |
| 权限与安全 | Phase 1 起 | T-10 / T-18 / T-31 | API Key 仅环境变量;Raw headers 脱敏;前端只接收过滤后数据;所有导出/分析记录 user_id |
| 错误与降级 | 全部 | T-05a / T-10 / T-23 / T-27 | UI 不得静默隐藏失败/陈旧/推断数据;Linter/类型检查/CI 在每个阶段闸门一并跑 |
| OpenLineage | Phase 4 | T-28 | Finding→Evidence→Feature→Observation→Raw 完整可视;含 column lineage |
| 文档同步 | 全部 | — | 每个 Phase 闸门 `docs/phase-N-gate.md` 必出 |
| 存储后端透明性(`StorageBackend` Protocol) | Phase 6 起 | T-37 / T-38 / T-46 | 业务层通过 Protocol 访问数据,`PIT_STORAGE_BACKEND=duckdb\|polars` 切换;小数据集本地开发仍可用 Polars |
| 真实数据管道(Yahoo/Polygon) | Phase 6 起 | T-34 / T-35 / T-36 | 适配器层抽象 `fetch()` 接口;面板从 manifest 升级到 real;增量 sync 幂等 |
| 本地 CI/CD(非 GitHub Actions) | Phase 7 起 | T-41 / T-42 | `ci-local.sh` 全流程 + `smoke-test.sh` 冒烟 + `pre-commit-check.sh` 快速检查 |
| CLI→前端功能等价 | Phase 7 起 | T-48~T-53 | CLI 保留为高级用途,UI 成为一等公民;所有异步任务写 `structlog` 结构化日志 |
| SSE 进度推送(前端 EventSource) | Phase 7 起 | T-46 / T-48 / T-14 | T-14 落地基础 SSE 端点;T-46 扩展面板构建 SSE;T-48 前端 EventSource 订阅 |

---

## 4. 风险与待澄清

| # | 风险 | 谁拍板 | 默认建议 |
|:--|:--|:--|:--|
| R-1 | 是否一上来就跑 GitHub Actions / GitLab CI,还是先本地 | Mavis | **已决定**:v2.0 全程本地 CI(docker compose + shell 脚本),不接 GitHub Actions(PRD v2.0 非功能需求明确);T-41 `ci-local.sh` 落地 |
| R-2 | LLM Provider 优先级:OpenAI / Gemini / Local | 用户 | 建议主用 OpenAI,Local 走 Ollama 做兜底 |
| R-3 | Yahoo Finance 延迟/限流/空数据 | 用户 | 已在 T-05a 落地降级路径:限流 / 空数据 / 错误三态分别有显式 `quality_status`,Panel 允许该标的缺失但在 `quality_report.json` 显式记录;双决策时钟(`1605_ET` / `1805_ET`)区分盘中与收盘价 |
| R-4 | 多 `coder` worker 并行起点 | Mavis | Phase 0 全程手干;Phase 1 起开 `mavis team plan` 拉多 worker |
| R-5 | 13F/8-K 等 SEC 数据的"事件频"建模粒度 | 用户 | 已在 T-26 明确:`available_at` = EDGAR `acceptancedatetime`;缺失时回落 `filing_date` + 保守规则 + `INFERRED_AVAILABILITY` 标签 |
| R-6 | 是否引入 ClickHouse / StarRocks 替代 DuckDB 用于 Phase 5 | Mavis | Phase 5 前重评数据量,DuckDB 顶得住就不动 |
| R-7 | FINRA Reg SHO 真实发布延迟可能 > T+1(节假日 / 系统故障) | Coder | 已在 T-05d 落 `finra_regsho_t_plus_1_afternoon`(14:00 ET)规则;若发现实际发布晚于 T+1 14:00 ET,Verifier 反馈回 Mavis,改 `t_plus_2_afternoon` 或更晚,同步 T-12 专项 case 11 |
| R-8 | Yahoo Finance 16:00 ET 收盘切换边界的 `decision_clock` 实现复杂度 | Coder | T-05a 优先实现 `1805_ET`(收盘后确定价),`1605_ET` 作为可选时钟;若盘中延迟报价 API 不稳定,Phase 1 末讨论是否砍掉 `1605_ET` |
| R-9 | FRED/ALFRED Adapter 误调 FRED 主 API(无 `realtime_start`)| Coder | 已在 T-05b 强制 ALFRED + T-12 case 12 防御;Adapter 启动时校验 `realtime_start` 必填,缺失直接报错;Verifer 单独跑 case 12 复测 |
| R-10 | ETF `shares_outstanding` T+1 误用 T 日(State Street vs BlackRock 混用) | Coder | 已在 T-26 强制各发行方独立 rule + T-12 case 14 防御;ETF 标的注册时必填 `issuer` 字段,Adapter 按 `issuer` 路由 availability rule |
| R-11 | FINRA `total_volume` 与 SIP tape 混用,夸大 `short_ratio` | Coder | 已在 T-05d 语义警告 + T-08 多源分母同源 + T-22 LLM 验证规则第 6 条覆盖;Evidence `semantic_caveat_zh` 与 LLM `limitations_zh` 必含“非全市场” |
| R-12 | Polygon API 免费套餐限速/配额不足 | 用户 | T-34 适配器已含指数退避 + 限流处理;若配额不足,可降级为仅 Yahoo + 缓存历史数据 |
| R-13 | DuckDB 单文件并发写入冲突 | Coder | T-37 已在验收中新增并发写入压力测试(2 进程同时 `upsert` 不报锁);写入路径统一收敛到 `duckdb_engine.py` 单例 + 进程级文件锁;若仍报 `database is locked`,评估 DuckDB 写入队列或回退 PostgreSQL |
| R-14 | 本地 CI 脚本在 Windows 下兼容性 | General | T-41 提供 `.sh` 主版本,同时提供 PowerShell 等效脚本(`scripts/ci-local.ps1`);docker compose 跨平台 |
| R-15 | 前端 6 大页面开发工期与并行度 | Mavis | T-48~T-53 可并行开发(各页面独立路由);建议先完成 T-47(公共组件)再开多 worker |

---

## 5. 启动指令(用户确认后执行)

待用户确认本 TODO 后,下一步动作(任选其一):

- **A. 启动 Phase 6 实施**:Mavis 先推 T-34(真实数据适配器)+ T-37(DuckDB 存储层),两条关键路径并行。
- **B. 启动 Phase 7 M3 并行推进**:T-41(本地 CI 脚本)+ T-42(pre-commit hook) 可与 Phase 6 同步开工。
- **C. 调整本 TODO**:增删条目、改优先级、调节奏。
- **D. 直接开 `mavis team plan` 并行多 worker**:Phase 6 + Phase 7 M3 可并行。

> **当前状态**:等待用户在 R-12 / R-13 / R-14 上拍板,以及 A/B/C/D 选一。
>
> **默认超时决定**:若 24 小时内无回复,默认执行 **A + B 并行**(启动 Phase 6 实施 + Phase 7 M3 本地 CI 同步推进),Mavis 不再阻塞等待。
