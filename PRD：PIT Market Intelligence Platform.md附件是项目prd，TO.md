<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# PRD：PIT Market Intelligence Platform.md附件是项目prd，TODO.md是项目开发todo list，todo list有什么地方可以优化，项目的数据获取和清洗是否符合逻辑和准确性。

基于对 PRD 和 TODO 的全面阅读，以下是详细分析：

***

## TODO 优化建议

### 任务结构与粒度问题

当前 TODO 整体设计良好，但存在以下可优化点：

**1. T-05（P0数据源Adapter）粒度过粗**[^1]
4个 Adapter（yfinance、FRED/ALFRED、CFTC COT、FINRA Reg SHO）聚合在同一个 Task 中，每个 Adapter 的实现难度差异极大。FRED/ALFRED 需要处理 real-time period 和 vintage 修订逻辑，CFTC COT 需要解析固定宽度文本格式，而 yfinance 仅封装 Python 库。建议拆分为 T-05a ～ T-05d，分别指定独立的验收标准和负责人，方便并行和独立 debug。

**2. T-08（Gold 基础特征）缺少窗口配置验收**[^1]
T-08 规定了 4 组特征（price/flow/macro/positioning），但没有要求验收"滚动窗口长度（如63日）需配置化，不硬编码"。PRD §4.1 强调任意 `decision_time` 的重建，若窗口长度硬编码，特征版本管理将失效。建议补充：`window_configs` 在 `metrics.yaml` 中可配置，且特征 `configuration_hash` 需覆盖窗口长度。

**3. T-09（PIT Panel Builder）与 T-12（防泄漏测试）责任矛盾**[^1]
T-09 由 Coder 完成，T-12 防泄漏测试也由 Coder 编写——这违背了 TODO 第0节"Verifier 不写代码，Coder 不自检"的核心纪律。防泄漏测试的 fixture 数据（即"伪造的 future-available 观测"）的构造权属不清晰。建议：Coder 写测试框架和 case 骨架，fixture 数据由 General 准备，Verifier 负责补充额外的 adversarial case。

**4. Phase 2 缺少 SSE 后端任务**[^1]
T-19 闸门要求"SSE 重连后根据 event ID 续传"，但 Phase 2 的 Task 列表中没有任何 SSE 后端实现任务（SSE 在 T-23 才出现，属于 Phase 3）。这意味着 Phase 2 闸门 V-19 的验收条件超前于实现计划，存在逻辑断层。建议在 T-14（Slice API）中补充 SSE 进度流端点的基础版本，或将 V-19 的 SSE 验收项移至 Phase 3 闸门。

**5. T-31（生产化基础设施）依赖链不完整**[^1]
T-31 新增 Redis/MinIO/PostgreSQL，但 T-14（Slice API 缓存键）在 Phase 2 已使用缓存逻辑，而此时 Redis 尚未引入。Phase 2 的缓存方案（内存缓存 vs. Redis）未明确，会导致 Phase 2 和 Phase 5 的缓存实现出现不一致。建议在 T-14 中明确 Phase 2 使用 in-process 内存缓存（如 `cachetools`），并在 T-31 中做 Redis 迁移。

**6. 缺少 Trading Calendar 独立 Task**[^1]
PRD §9.2 的资产图将 `trading_calendar` 作为独立的上游资产，但 TODO 中没有对应的 Task。交易日历对 Availability Resolver（T-07）、PIT Panel Builder（T-09）和前视偏差测试（T-12）都是关键依赖，缺失会导致非交易日的 `available_at` 推算错误。建议在 Phase 0 或 Phase 1 早期增加 `T-03b · Trading Calendar 初始化`。

**7. 风险表 R-3 对 Yahoo Finance 的处置不够具体**[^1]
"接受延迟，关键决策上 FRED/官方源兜底"是策略声明，但没有对应 Task 实现降级逻辑。当 yfinance 限流或返回空数据时，Silver 层的 `quality_status` 应如何标记、Panel 如何处理缺失标的，当前无具体设计。建议在 T-05/T-06 中明确：yfinance 失败 → `quality_status = SOURCE_FAILED`，Panel 允许部分标的缺失但需在 `quality_report.json` 中显式记录。

***

## 数据获取与清洗的逻辑和准确性分析

### 准确性较好的设计

**FRED/ALFRED 双时间处理**[^2]
PRD 明确要求同时保存 `observation_time`（数据观察期）、`release_time`（官方发布时间）和 `available_at`（实际可得时间），这是处理宏观数据修订的标准做法。ALFRED（Archival FRED）的 real-time period 机制确实允许按发布 vintage 查询历史数据，设计逻辑正确。

**CFTC COT 的周五发布规则**[^1]
T-07 的 `cftc_friday_release` availability rule 正确反映了 CFTC 每周五下午 3:30 ET 发布上周二持仓数据的实际规律，PIT 逻辑能防止在发布前使用该周数据。

### 需要修正或补充的问题

**1. FINRA Reg SHO 的 `available_at` 推算存在风险**[^1]
TODO T-07 中 `finra_regsho_same_day` 规则暗示当日数据当日可得，但实际上 FINRA Reg SHO 短卖数据通常在交易日结束后 T+1 发布（次日发布前一交易日数据）。若将 `available_at` 设为观察当日，会引入约 1 个交易日的前视偏差。建议将规则改为 `finra_regsho_t_plus_1`，并在 T-12 防泄漏测试中增加专项 case。

**2. Yahoo Finance OHLCV 的 `available_at` 语义需明确**[^2]
PRD 数据源表标注 yfinance 为"日频"，但盘中数据和收盘后数据的 `available_at` 不同（收盘价在美东 16:00 后才最终确认，调整价可能在隔日修正）。当前 PRD 和 TODO 均未区分"实时延迟报价"与"收盘后确定价格"的 availability 差异，会影响基于 yfinance 价格构建的特征（如当日 Z-score）的 PIT 准确性。

**3. SEC 13F 的 `available_at` 需使用 filing acceptance time 而非 period of report**[^1]
TODO 风险表 R-5 已将此列为默认建议，但 T-26（P1 数据源）的验收条件并未明确要求从 SEC EDGAR 提取 `acceptancedatetime` 字段作为 `available_at`。13F 披露的 `period of report`（如2026-03-31）与实际提交/接受时间（如 2026-05-15）可相差45天，若用错字段会引入严重前视偏差。

**4. FINRA OTC 数据的语义警告需在特征层传播**[^2]
PRD §3 正确指出 FINRA short volume 不等同于 short interest，并在 Evidence 层设置 `semantic_caveat_zh`。但 TODO 中 T-08（Gold 特征）没有要求特征层继承该语义警告至 `feature_observations_bitemporal` 表的 `quality_flags_json`，导致语义警告仅存在于 Evidence Catalog 而非特征链路，增加了 LLM 绕过限制的风险。

**5. 前向填充（forward-fill）的风险未在 Silver 层显式控制**[^2]
PRD §8.2 的 `forward_fill_allowed: true` 和 `max_staleness: 10D` 目前属于 Metric Registry 配置，但 Silver 层的 `observations_bitemporal` 表没有 `is_forward_filled` 或 `fill_source_observation_id` 字段。当数据被前向填充后，Silver 层无法区分"观测到的值"和"推算值"，会导致 `quality_status` 状态不准确（STALE 状态在 Feature 层才出现，但追溯需要到 Silver）。建议在 Silver 表中增加 `fill_type: OBSERVED | FORWARD_FILLED | INTERPOLATED` 字段。

<div align="center">⁂</div>

[^1]: TODO-2.md

[^2]: PRD-PIT-Market-Intelligence-Platform.md

