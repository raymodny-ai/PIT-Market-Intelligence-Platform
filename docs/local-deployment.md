# Local Deployment Runbook

**Date**: 2026-07-22
**Target**: Windows 10/11 + PowerShell, Python 3.12, Node 20+
**Profile**: Development (no Docker, in-process cache, file-based storage)

> 完整 production 部署(Redis + MinIO + PostgreSQL + Dagster)见根目录 `docker-compose.yml`,
> 启动命令 `docker compose up -d`。本 runbook 覆盖单机开发部署。

---

## 0. 前置依赖

| 工具 | 最低版本 | 验证命令 | 备注 |
|:--|:--|:--|:--|
| Python | 3.12 | `python --version` | 路径示例:`C:\Users\raylan\AppData\Local\Programs\Python\Python312\python.exe` |
| Node.js | 20.x | `node --version` | 同步 npm ≥ 10 |
| Git | 2.40+ | `git --version` | Windows 通常 `C:\Program Files\Git\bin\git.exe` |
| (可选)Docker Desktop | 4.x | `docker --version` | 仅生产化需要 |

如果 git 不在 PATH,临时加:
```powershell
$env:Path = "C:\Program Files\Git\bin;" + $env:Path
```

Windows 终端的默认 GBK 编码会让 Rich 库的 `✓` 字符爆 `UnicodeEncodeError`,先设:
```powershell
$env:PYTHONIOENCODING = "utf-8"
```

---

## 1. 拉代码 & 装依赖

```powershell
git clone https://github.com/raymodny-ai/PIT-Market-Intelligence-Platform.git
cd "PIT-Market-Intelligence-Platform"

# 1) Python package + 全部可选依赖(开发 / ETL / LLM / 研究)
python -m pip install -e ".[dev,etl,llm,research]"

# 2) Frontend deps
cd frontend
npm install
cd ..
```

`pip install -e .` 会在 `Python\Python312\Scripts\` 装出 `pit-market.EXE` 入口(typer CLI)。

---

## 2. 启动后端 (FastAPI / uvicorn)

```powershell
$env:PYTHONPATH     = "src"
$env:PIT_CONFIG_DIR = "config"
$env:GOLD_PANELS_DIR = "data\gold\pit_panels"
$env:PYTHONIOENCODING = "utf-8"

python -m uvicorn pit_market.api.main:app --host 127.0.0.1 --port 8000 --log-level info
```

| 端点 | URL | 说明 |
|:--|:--|:--|
| `/health` | http://127.0.0.1:8000/health | 健康检查,带 `registry_hash` |
| OpenAPI | http://127.0.0.1:8000/docs | Swagger UI |
| `/v1/panels/{id}/slice` | POST | 切片 API(PIT 严格) |
| `/v1/lineage/{entity_id}` | GET | 5 级血缘图 |
| `/v1/analyses/{run_id}/stream` | GET | LLM 5 阶段 SSE |
| `/v1/sources/status` | GET | 数据源 SLA 状态 |

---

## 3. 启动前端 (Next.js)

```powershell
cd frontend
npm run dev          # 默认端口 3001(package.json 写死)
# 浏览器打开 http://127.0.0.1:3001
```

`package.json` 的 dev/start 都用 `-p 3001`,跟后端 8000 错开不冲突。
如果要让前端连到本地后端,前端代码读 `NEXT_PUBLIC_API_BASE` 环境变量(默认 `http://127.0.0.1:8000`)。

---

## 4. CLI 入口

```powershell
# 直接用 pip 装出的 console script
& "$env:LOCALAPPDATA\Programs\Python\Python312\Scripts\pit-market.EXE" --help

# 或用 python -m
python -m pit_market.cli --help
```

9 个一级命令:`init` / `refresh` / `pit` (build / replay) / `analyze` / `report` (build) / `export` / `healthcheck` / `backfill` / `backtest` (run)

实战示例:
```powershell
# 1) 健康检查
pit-market healthcheck

# 2) 重建一个 PIT panel
pit-market pit build --decision-time "2024-01-31T18:05:00Z" --universe "SPY,QQQ,GLD,SLV"

# 3) 把 panel 重跑(replay)
pit-market pit replay --panel-id cli-20240131T180500Z-SPY-QQQ-GLD-SLV

# 4) 出 frozen report
pit-market report build --panel-id cli-20240131T180500Z-SPY-QQQ-GLD-SLV --title "Demo"

# 5) 跑 walk-forward 回测(线性 baseline)
pit-market backtest run `
  --features .\demo\features.csv `
  --target .\demo\target.csv `
  --feature-cols "f1,f2" `
  --train 200 --test 30 --step 30
```

---

## 5. Smoke test(端到端)

后端起来后跑这一组 curl 验证 18 个 endpoint:

```powershell
$base = "http://127.0.0.1:8000"

# health
(Invoke-WebRequest "$base/health").Content
# → {"status":"ok","version":"0.1.0","registry_hash":"..."}

# instruments(应返回 12 个 canonical_symbol)
(Invoke-WebRequest "$base/v1/instruments/registry").Content | ConvertFrom-Json |
  Select-Object -ExpandProperty instruments | Format-Table

# metrics(14 个 field_name)
(Invoke-WebRequest "$base/v1/metrics/registry").Content | ConvertFrom-Json |
  Select-Object -ExpandProperty fields | Format-Table

# lineage(5 级图)
(Invoke-WebRequest "$base/v1/lineage/test").Content
# → {"entity_id":"test","graph":{"nodes":[...5 个]...},...}

# source health
(Invoke-WebRequest "$base/v1/sources/status").Content
```

前端 8 个路由:
```powershell
$routes = "/","/dashboard","/dashboard/replay","/health","/lineage/test","/panels/test","/reports/test","/findings/test"
foreach ($r in $routes) {
  (Invoke-WebRequest "http://127.0.0.1:3001$r").StatusCode
}
# 全部应返回 200
```

---

## 6. 已知本地限制(无 Docker)

| 功能 | 状态 | 影响 |
|:--|:--|:--|
| Cache 后端 | InProcessCache(cachetools) | 不跨进程;重启清空 |
| 对象存储 | 文件系统 `data/` | 替代 MinIO;单机足够 |
| 元数据 DB | 文件系统 | 替代 PostgreSQL;单机足够 |
| Dagster | 未启动 | ETL 调度需手动跑 CLI;`pit-market refresh` / `backfill` |
| Feishu 通知 | 不发(无 webhook) | Notifier 静默记录到 `Notifier.sent` |
| 鉴权 | dev keys(API Key `rk_dev_researcher` 等) | 见 `src/pit_market/auth/permissions.py` |

要切到生产 Redis 后端:
```powershell
$env:PIT_MARKET_CACHE_BACKEND = "redis"
$env:PIT_MARKET_REDIS_URL     = "redis://localhost:6379/0"
python -m uvicorn pit_market.api.main:app --port 8000
```
代码侧零改动(`build_cache()` 工厂按 env 切换)。

---

## 7. 验证清单

部署完跑这一组,全过才算 ok:

- [ ] `python -m pytest tests/ -q` → 346 passed
- [ ] `ruff check src tests` → All checks passed
- [ ] `mypy src` → no issues found in 44 source files
- [ ] `npm run build`(在 `frontend/`)→ 9 routes compiled
- [ ] `pit-market healthcheck` → 4 P0 源表格正常
- [ ] 后端 `/health` → 200,`registry_hash` 非空
- [ ] 前端 http://127.0.0.1:3001/ → 200,标题 "PIT Market Intelligence"
- [ ] `pit-market pit build` → 写出 `data/gold/pit_panels/*_manifest.json`
- [ ] `pit-market report build` → 写出 `data/gold/reports/*.json`

---

## 8. 故障排查

| 症状 | 原因 | 修法 |
|:--|:--|:--|
| `git : 无法识别` | 不在 PATH | 临时:`$env:Path = "C:\Program Files\Git\bin;" + $env:Path` |
| `UnicodeEncodeError ... \u2713` | Windows GBK | `$env:PYTHONIOENCODING = "utf-8"` |
| `ModuleNotFoundError: pit_market` | 没装包或没设 PYTHONPATH | `pip install -e .` 或 `$env:PYTHONPATH = "src"` |
| 后端启动报 `Registry load failed` | `PIT_CONFIG_DIR` 路径错 | `cd` 到项目根目录,`$env:PIT_CONFIG_DIR = "config"` |
| 前端报 `connection refused` | 后端没起或端口错 | 看 `NEXT_PUBLIC_API_BASE` 是否 = `http://127.0.0.1:8000` |
| `redis.exceptions.ConnectionError` | 切到 redis 后端但 redis 没起 | 设回 `$env:PIT_MARKET_CACHE_BACKEND = "inprocess"` |
| `numpy` / `pandas` mypy 报错 | python_version 用了 3.11 | `pyproject.toml` 设 `python_version = "3.12"` |

---

## 9. 进程管理(开发期)

两个服务用 `run_in_background` 启的可以这样关:

```powershell
Get-Process -Name uvicorn,node | Stop-Process -Force
```

或者用我(Mavis)提供的脚本化:
```powershell
# 启动
.\scripts\dev-start.ps1

# 停止
.\scripts\dev-stop.ps1
```
(脚本见 `scripts/` 目录,如未提供可手起手停)

---

## 10. 部署拓扑图

```
┌────────────────────────────────────────────────────┐
│  Browser  →  http://127.0.0.1:3001 (Next.js dev)  │
└──────────────────────┬─────────────────────────────┘
                       │  fetch /v1/*
                       ▼
┌────────────────────────────────────────────────────┐
│  FastAPI  →  127.0.0.1:8000  (uvicorn)            │
│  ├─ /health  /v1/panels/...                        │
│  ├─ /v1/slice  /v1/lineage  /v1/analyses/stream   │
│  └─ /v1/sources/status  /v1/export/...             │
└──────┬─────────────┬─────────────┬────────────────┘
       │             │             │
       ▼             ▼             ▼
   ┌────────┐   ┌──────────┐  ┌────────────┐
   │ config │   │ data/*   │  │ InProcess  │
   │ yaml + │   │ raw/     │  │ Cache      │
   │ schema │   │ silver/  │  │ (cachetools│
   │        │   │ gold/    │  │  TTL)      │
   └────────┘   └──────────┘  └────────────┘
```

生产版本只是把 InProcessCache 换 Redis,`data/` 换 MinIO/Postgres,加 Dagster 调度;**业务代码零改动**(`CacheBackend` Protocol 隔离)。
