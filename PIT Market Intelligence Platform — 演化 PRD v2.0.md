<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# [https://github.com/raymodny-ai/PIT-Market-Intelligence-Platform](https://github.com/raymodny-ai/PIT-Market-Intelligence-Platform) 为这个项目 未来工作做一个演化prd，具体要实现的点如下：

1、真实历史数据接入: 仓库里的 data/gold/pit_panels/ 是 CLI 一次性生成的 manifest-only 面板,真正接 Yahoo/Polygon historical parquet 是下一步
2、DuckDB backend: 当前 builder 走 in-memory Polars,大 universe (>500 symbols) 需要切到 DuckDB
3、生产模式验证: npm run build + next start 完整 prod mode 还没在 CI 跑过
CI/CD: 在本地运行，不要GitHub Actions。
4、OpenAPI 文档: /docs Swagger UI 已可访问,但 README 里 curl examples 可再扩 5、CLI 工具改为在前端交互设计。具体实现项目用cli工具实现的任务都要在前端有相关功能实现，比如子命令用途pit build构建 PIT 面板 (见 §4)pit replay历史时刻 replaypit report build生成投资报告 (MD / PDF)pit backtest run跑回测(更多)注册表查询 / 健康检查 / 数据导出。@GitHub

基于对仓库结构的分析，以下是针对 [PIT Market Intelligence Platform](https://github.com/raymodny-ai/PIT-Market-Intelligence-Platform) 的**演化 PRD（进化式产品需求文档）**，聚焦于你列出的5个未来工作方向。

***

# PIT Market Intelligence Platform — 演化 PRD v2.0

**文档状态**: 草稿 · 2026-07-23
**范围**: 基于现有 v1 基础，向生产级平台演进

***

## 背景与演化目标

当前 v1 已实现：manifest-only PIT 面板生成、in-memory Polars builder、FastAPI + Next.js 前端骨架、CLI 工具链 (`pit build / replay / report / backtest`)。v2 演化目标是打通**真实数据管道 → 大规模存储 → 生产部署 → 全前端交互**的完整闭环，同时将所有 CLI 能力提升为一等公民 UI 功能。

***

## Epic 1 — 真实历史数据接入

### 背景

`data/gold/pit_panels/` 目前存储的是 CLI 一次性生成的 manifest-only 面板（仅含元数据，无真实行情）。需要接入 Yahoo Finance 和 Polygon.io 的真实历史 Parquet 数据，使面板具备实际分析价值。

### 用户故事

- 作为分析师，我希望在面板中看到真实 OHLCV + 调整后收盘价，而非占位符数据
- 作为系统管理员，我希望增量拉取增量数据（delta update），避免重复全量下载


### 功能需求

**F1.1 — 数据源适配器层**

```
src/pit/data/adapters/
  ├── yahoo_adapter.py        # yfinance wrapper，输出标准化 Parquet
  ├── polygon_adapter.py      # Polygon REST v2 历史聚合，支持分钟/日线
  └── base_adapter.py         # 抽象接口: fetch(symbol, start, end, freq) -> pl.DataFrame
```

- 统一输出 schema：`{symbol, date, open, high, low, close, volume, adj_close, source}`
- 支持 `freq` 参数：`1d / 1h / 1m`
- Polygon 适配器需处理分页（`next_url` cursor 翻页）

**F1.2 — PIT 面板升级：manifest → real data**

- `pit build` 执行时，检测 `panel_type: real | manifest`，若为 real 则调用适配器拉取
- 拉取结果以 Parquet 写入 `data/{asset_class}/{symbol}/raw/{freq}/YYYY-MM.parquet`（按月分区）
- 支持 `--source yahoo|polygon|auto`（auto = Yahoo 优先，失败降级 Polygon）

**F1.3 — 增量更新调度**

- 提供 `pit sync --symbol GC=F --since 2025-01-01` 命令（同时在前端"数据管理"页触发）
- 记录每个 symbol 的 `last_fetched_at` 到 DuckDB `data_registry` 表
- 支持 dry-run 模式：`--dry-run` 打印待下载范围，不实际写盘


### 验收标准

- [ ] `pit build --panel gold --source yahoo` 生成包含真实收盘价的 Parquet，可在前端 PIT 面板页展示时间序列图
- [ ] 单 symbol 全量拉取（10年日线）耗时 < 5s
- [ ] 数据 schema 验证：空值率 < 0.1%，价格连续性检查（涨跌幅 > 50% 告警）

***

## Epic 2 — DuckDB 后端替换

### 背景

当前 builder 使用 in-memory Polars，当 universe > 500 symbols 时内存压力超出合理范围（估算 500 symbols × 10年日线 ≈ 2-3 GB）。DuckDB 提供零配置、文件级持久化、原生 Parquet 查询能力，是最合适的替换方案。

### 用户故事

- 作为量化研究员，我希望对 1000+ symbols 进行横截面因子计算，不受内存限制
- 作为 API 消费者，我希望通过 SQL 接口直接查询 PIT 面板，无需加载整个数据集


### 功能需求

**F2.1 — DuckDB 存储层**

```
src/pit/storage/
  ├── duckdb_engine.py        # 单例连接管理，db 路径从 .env PIT_DUCKDB_PATH 读取
  ├── panel_store.py          # 封装 CRUD: upsert_panel(), query_panel(), list_panels()
  └── migrations/
      └── 001_init_schema.sql  # panels, data_registry, replay_snapshots, backtest_runs 表
```

- DuckDB 直接查询 Parquet 目录：`SELECT * FROM read_parquet('data/gold/**/*.parquet')`
- 保留 Polars 作为计算层（DuckDB → Arrow → Polars 零拷贝）
- 提供 `PIT_STORAGE_BACKEND=duckdb|polars` 环境变量切换，方便小数据集本地开发仍用 Polars

**F2.2 — API 层适配**

- FastAPI 路由中所有 `build_panel()` 调用替换为 `panel_store.query_panel()`
- 新增 `/api/v1/sql` 端点（仅开发模式启用）：接受 read-only DuckDB SQL，返回 JSON
- 查询超时限制：30s，结果集上限：10,000 行

**F2.3 — 性能基准**


| 场景 | Polars in-memory | DuckDB 目标 |
| :-- | :-- | :-- |
| 500 symbols 全量加载 | OOM / >30s | < 3s |
| 单因子横截面计算（500×2520行） | ~2s | < 1s |
| 历史 replay 快照生成 | ~5s | < 2s |

### 验收标准

- [ ] `PIT_STORAGE_BACKEND=duckdb pytest tests/storage/` 全部通过
- [ ] 1000 symbols 日线 5 年数据加载内存占用 < 500 MB
- [ ] 现有 API 响应格式不变（向后兼容）

***

## Epic 3 — 生产模式验证（本地 CI/CD）

### 背景

`npm run build + next start` 完整 prod mode 未经系统验证。CI/CD 采用**本地运行**方案（不使用 GitHub Actions），基于 `docker compose` + shell 脚本实现可重复的构建/测试/部署流水线。

### 用户故事

- 作为开发者，我希望一条命令完成完整的构建+测试+启动验证
- 作为团队负责人，我希望每次 `git commit` 前自动跑冒烟测试（pre-commit hook）


### 功能需求

**F3.1 — 本地 CI 脚本**

```
scripts/
  ├── ci-local.sh             # 主流水线脚本
  ├── smoke-test.sh           # 生产模式冒烟测试
  └── pre-commit-check.sh     # git hook 调用的快速检查
```

`ci-local.sh` 执行顺序：

1. `docker compose build --no-cache` — 全量构建镜像
2. `docker compose run --rm api pytest tests/ -x -q` — Python 测试
3. `docker compose run --rm frontend npm run build` — Next.js prod build
4. `docker compose up -d` — 启动所有服务
5. `bash scripts/smoke-test.sh` — 端到端冒烟测试
6. `docker compose down` — 清理

**F3.2 — 冒烟测试覆盖**

`smoke-test.sh` 验证以下端点（使用 `curl` + `jq`）：

```bash
# API 健康检查
curl -f http://localhost:8000/health

# PIT 面板列表
curl -f http://localhost:8000/api/v1/panels

# 前端 prod 页面可达
curl -f http://localhost:3000

# OpenAPI schema 可达
curl -f http://localhost:8000/docs
curl -f http://localhost:8000/openapi.json
```

**F3.3 — Git Pre-commit Hook**

`scripts/pre-commit-check.sh` 快速检查（< 60s）：

- `ruff check src/` — Python lint
- `mypy src/pit/ --ignore-missing-imports` — 类型检查
- `cd frontend && npm run lint` — ESLint
- `pytest tests/unit/ -x -q --timeout=30` — 仅跑单元测试

安装方式：`ln -s ../../scripts/pre-commit-check.sh .git/hooks/pre-commit`

### 验收标准

- [ ] `bash scripts/ci-local.sh` 在干净环境从零执行完整通过
- [ ] 冒烟测试所有 curl 返回 HTTP 200
- [ ] pre-commit hook 在 `git commit` 时自动触发，失败时阻止提交

***

## Epic 4 — OpenAPI 文档扩展

### 背景

`/docs` Swagger UI 已可访问，但 README 中的 `curl` 示例覆盖不足，缺少完整的请求/响应示例和错误码文档。

### 功能需求

**F4.1 — FastAPI 路由注解增强**

为所有路由添加：

- `summary`、`description`、`tags`
- `response_model` 明确指定 Pydantic schema
- `responses` 字典覆盖 400/404/422/500 错误码及示例 body

示例：

```python
@router.post(
    "/panels/build",
    summary="构建 PIT 面板",
    description="触发 PIT 面板构建任务，支持实时 SSE 进度推送",
    tags=["panels"],
    response_model=BuildResponse,
    responses={
        422: {"description": "参数校验失败", "model": ErrorDetail},
        503: {"description": "数据源不可达"},
    }
)
```

**F4.2 — README curl 示例扩展**

在 README `## API Quick Reference` 章节补充以下示例：


| 操作 | curl 命令 |
| :-- | :-- |
| 健康检查 | `curl http://localhost:8000/health` |
| 列出所有面板 | `curl http://localhost:8000/api/v1/panels` |
| 构建面板 | `curl -X POST .../panels/build -d '{"asset":"gold","source":"yahoo"}'` |
| 触发 replay | `curl -X POST .../replay -d '{"panel_id":"...","as_of":"2024-01-15"}'` |
| 生成报告 | `curl -X POST .../report/build -d '{"panel_id":"...","format":"pdf"}'` |
| 跑回测 | `curl -X POST .../backtest/run -d '{"strategy":"momentum","panel_id":"..."}'` |
| 数据导出 | `curl http://localhost:8000/api/v1/export/csv?panel_id=...` |

### API Quick Reference

以下 curl 示例假设后端运行在 `http://localhost:8000`。所有 POST 请求使用 JSON body。

```bash
# 1. 健康检查
curl http://localhost:8000/health

# 2. 列出所有面板
curl http://localhost:8000/api/v1/panels

# 3. 构建面板（异步任务，返回 job_id）
curl -X POST http://localhost:8000/api/v1/panels/build \
  -H "Content-Type: application/json" \
  -d '{"symbols":["SPY","GLD"],"force_rebuild":false}'

# 4. 查看面板历史快照
curl http://localhost:8000/api/v1/panels/<panel_id>/snapshots

# 5. 生成报告（异步任务）
curl -X POST http://localhost:8000/api/v1/report/build \
  -H "Content-Type: application/json" \
  -d '{"panel_id":"cli-20240229T180500Z-SPY-GLD","language":"zh"}'

# 6. 运行回测（异步任务）
curl -X POST http://localhost:8000/api/v1/backtest/run \
  -H "Content-Type: application/json" \
  -d '{"strategy":"momentum_5d","symbols":["SPY","QQQ"],"start_date":"2020-01-01","end_date":"2024-01-01"}'

# 7. 数据导出（CSV / Parquet）
curl -O http://localhost:8000/api/v1/export/csv?panel_id=cli-20240229T180500Z-SPY-GLD
curl -O http://localhost:8000/api/v1/export/parquet?panel_id=cli-20240229T180500Z-SPY-GLD

# 8. 查看系统健康
curl http://localhost:8000/api/v1/system/health

# 9. 查看后台任务列表
curl http://localhost:8000/api/v1/system/tasks

# 10. 取消任务
curl -X POST http://localhost:8000/api/v1/system/tasks/<job_id>/cancel

# 11. 触发数据同步
curl -X POST http://localhost:8000/api/v1/sync \
  -H "Content-Type: application/json" \
  -d '{"symbols":["SPY","GLD"],"full_refresh":false}'

# 12. Swagger UI (浏览器访问)
open http://localhost:8000/docs

# 13. OpenAPI schema
curl http://localhost:8000/openapi.json
```

**F4.3 — 独立 API 文档站**

- 在 `docs/api/` 目录生成静态 OpenAPI HTML（使用 `redocly build-docs`）
- 支持 `pit docs serve` 命令在本地 `localhost:8080` 启动文档站


### 验收标准

- [ ] Swagger UI 所有端点有 summary + 至少一个响应示例
- [ ] README curl 示例覆盖全部 7 类操作，均可复制粘贴执行
- [ ] `pit docs serve` 可在本地访问完整 Redoc 站

***

## Epic 5 — CLI → 前端 UI 全功能迁移

### 背景

现有 CLI 工具（`pit build / replay / report / backtest`）是平台核心功能的唯一交互入口。v2 要求**所有 CLI 子命令对应的功能在前端有完整实现**，CLI 保留为高级/脚本用途，UI 成为一等公民。

### 信息架构（前端导航）

```
PIT Platform
├── 📊 面板管理          ← pit build
│   ├── 面板列表 / 创建
│   ├── 构建进度（SSE 实时）
│   └── 数据管理（sync / 增量更新）
├── ⏪ 历史 Replay       ← pit replay
│   ├── 时间轴选择器
│   ├── 快照对比视图
│   └── Replay 导出
├── 📄 报告生成          ← pit report build
│   ├── 报告配置表单
│   ├── MD / PDF 预览
│   └── 报告历史列表
├── 🔄 回测工作台        ← pit backtest run
│   ├── 策略配置
│   ├── 结果图表（收益曲线、Sharpe、最大回撤）
│   └── 回测历史对比
├── 🗂️ 注册表            ← pit registry query
│   ├── Symbol 搜索
│   ├── 面板元数据查看
│   └── 数据导出（CSV / Parquet）
└── ⚙️ 系统              ← pit health / status
    ├── 服务健康监控
    ├── 任务队列状态
    └── 环境配置查看
```


### 功能需求

**F5.1 — 面板管理页（对应 `pit build`）**

- 表单字段：asset class、symbol list（多选 + 自定义输入）、数据源（Yahoo/Polygon）、时间范围、频率
- 点击"构建"后通过 `EventSource` 订阅 `/api/v1/panels/build/stream`，实时展示进度条 + 日志
- 面板列表支持：排序、过滤（按状态/资产类）、一键删除/重建

**F5.2 — 历史 Replay 页（对应 `pit replay`）**

- 时间轴滑块（日级粒度，范围选择）
- 左右双面板对比：选择两个历史时刻的面板快照
- 变化高亮：相对于基准日期的因子值变化（红/绿色）
- 导出当前快照为 CSV

**F5.3 — 报告生成页（对应 `pit report build`）**

- 支持模板选择：`summary | detailed | custom`
- 实时 Markdown 预览（右侧面板，react-markdown 渲染）
- "生成 PDF" 按钮调用后端 `/api/v1/report/build?format=pdf`，触发浏览器下载
- 报告历史：列出已生成报告，支持重新下载

**F5.4 — 回测工作台（对应 `pit backtest run`）**

- 策略配置表单：策略类型（动量/均值回归/自定义）、参数面板（lookback window、rebalance freq 等）
- 提交后异步执行，任务状态通过轮询 `/api/v1/backtest/{job_id}` 跟踪
- 结果展示：
    - 累计收益曲线（Recharts 折线图）
    - 年化 Sharpe、最大回撤、胜率 KPI 卡片
    - 持仓权重热力图
- 多次回测结果可叠加对比

**F5.5 — 注册表 \& 数据导出（对应 `pit registry query` / `pit export`）**

- Symbol 搜索框（支持模糊匹配，调用 `/api/v1/registry/search?q=`）
- 面板元数据详情面板（schema、行数、时间范围、数据源、last_fetched_at）
- 导出按钮：CSV（直接下载）/ Parquet（后端打包后下载）

**F5.6 — 系统健康页（对应 `pit health`）**

- 实时健康卡片：API、DuckDB、数据源连通性（Yahoo/Polygon ping）
- 任务队列：当前运行/排队/失败的异步任务列表，支持手动取消
- 环境信息：版本号、Python/Node 版本、`PIT_STORAGE_BACKEND` 当前值


### 前端技术选型

| 需求 | 方案 |
| :-- | :-- |
| 实时进度推送 | `EventSource` (SSE) |
| 图表 | `Recharts`（已有依赖） |
| 表单 | `react-hook-form` + `zod` 校验 |
| Markdown 预览 | `react-markdown` + `remark-gfm` |
| 时间轴滑块 | `@radix-ui/react-slider` |
| 异步任务状态 | SWR 轮询 (`refreshInterval: 2000`) |

### 验收标准

- [ ] 前端所有 5 个主页面功能完整，无"施工中"占位符
- [ ] `pit build` 能做的事，通过面板管理页 UI 操作完全等价
- [ ] 回测结果图表在 Chrome/Firefox 渲染正常
- [ ] 所有表单提交有 loading 状态 + 错误提示（toast 通知）
- [ ] 前端 prod build (`npm run build`) 零 error，warning < 10 条

***

## 里程碑规划

| 里程碑 | 包含 Epic | 目标状态 |
| :-- | :-- | :-- |
| **M1** — 数据真实化 | Epic 1 | Yahoo/Polygon 数据可写入 Parquet，面板含真实行情 |
| **M2** — 存储升级 | Epic 2 | DuckDB 替换完成，500+ symbols 性能达标 |
| **M3** — 生产就绪 | Epic 3 + Epic 4 | 本地 CI 脚本一键通过，OpenAPI 文档完整 |
| **M4** — UI 完整 | Epic 5 | 所有 CLI 功能在前端有完整等价实现 |

> **依赖关系**：M1 → M2（DuckDB 存真实数据）→ M4（前端展示真实数据）；M3 可与 M1/M2 并行推进。

***

## 非功能需求

- **安全**：`/api/v1/sql` 端点仅限开发模式，生产模式必须关闭；Polygon API key 通过 `.env` 注入，不得硬编码
- **可观测性**：所有异步任务写结构化日志（`structlog`），包含 `job_id`、`symbol`、`duration_ms`
- **向后兼容**：CLI 工具全部保留，v2 不删除任何现有 CLI 子命令
- **本地优先**：CI/CD 全部基于本地 docker compose + shell 脚本，不引入 GitHub Actions 依赖

