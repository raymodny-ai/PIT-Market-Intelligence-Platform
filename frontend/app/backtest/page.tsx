"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  triggerBacktest,
  fetchBacktestResult,
  fetchSystemTasks,
  cancelTask,
} from "../../lib/api";
import { queryKeys } from "../../lib/queryKeys";
import type { BacktestResult } from "../../types/api";

const STRATEGIES = [
  { value: "momentum_5d", label: "5日动量" },
  { value: "mean_revert_21d", label: "21日均线回归" },
  { value: "cot_extreme", label: "COT 极端信号" },
  { value: "multi_factor", label: "多因子组合" },
];

export default function BacktestPage() {
  const [strategy, setStrategy] = useState(STRATEGIES[0].value);
  const [symbols, setSymbols] = useState("SPY,QQQ,GLD");
  const [startDate, setStartDate] = useState("2020-01-01");
  const [endDate, setEndDate] = useState("2024-01-01");
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const qc = useQueryClient();

  const { data: tasks } = useQuery({
    queryKey: queryKeys.tasks(),
    queryFn: fetchSystemTasks,
    staleTime: 10_000,
    refetchInterval: 5000,
  });

  const { data: result } = useQuery({
    queryKey: queryKeys.backtestResult(activeJobId!),
    queryFn: () => fetchBacktestResult(activeJobId!),
    enabled: !!activeJobId,
    staleTime: 300_000,
  });

  const handleRun = async () => {
    setSubmitting(true);
    const symList = symbols.split(",").map((s) => s.trim()).filter(Boolean);
    const task = await triggerBacktest({
      strategy,
      symbols: symList,
      start_date: startDate,
      end_date: endDate,
    });
    setSubmitting(false);
    if (task) {
      setActiveJobId(task.job_id);
      qc.invalidateQueries({ queryKey: queryKeys.tasks() });
    }
  };

  const handleCancel = async (jobId: string) => {
    await cancelTask(jobId);
    qc.invalidateQueries({ queryKey: queryKeys.tasks() });
  };

  const btTasks = tasks?.filter((t) => t.task_type === "backtest") ?? [];

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-xl font-bold text-ink-900">回测工作台</h1>
        <p className="text-sm text-ink-500 mt-1">
          配置策略参数，使用 PIT 安全数据进行历史回测
        </p>
      </div>

      {/* Config form */}
      <div className="card-pad mb-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          <div>
            <label className="label-muted block mb-1.5">策略</label>
            <select className="input" value={strategy} onChange={(e) => setStrategy(e.target.value)}>
              {STRATEGIES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label-muted block mb-1.5">标的 (逗号分隔)</label>
            <input className="input" value={symbols} onChange={(e) => setSymbols(e.target.value)} />
          </div>
          <div>
            <label className="label-muted block mb-1.5">起始日期</label>
            <input className="input" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          <div>
            <label className="label-muted block mb-1.5">结束日期</label>
            <input className="input" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </div>
        </div>
        <div className="mt-4">
          <button className="btn-primary" onClick={handleRun} disabled={submitting}>
            {submitting ? "提交中..." : "运行回测"}
          </button>
        </div>
      </div>

      {/* Results */}
      {result && (
        <div className="mb-6">
          <h2 className="text-sm font-semibold text-ink-700 mb-3">回测结果</h2>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <ResultCard label="总收益" value={formatPct(result.total_return)} />
            <ResultCard label="夏普比率" value={formatNum(result.sharpe_ratio)} />
            <ResultCard label="最大回撤" value={formatPct(result.max_drawdown)} />
            <ResultCard label="胜率" value={formatPct(result.win_rate)} />
            <ResultCard label="交易次数" value={result.trade_count?.toString() ?? "—"} />
          </div>
        </div>
      )}

      {/* Task history */}
      <h2 className="text-sm font-semibold text-ink-700 mb-3">回测任务</h2>
      {!btTasks.length ? (
        <div className="card-pad text-center py-8">
          <p className="text-sm text-ink-500">暂无回测任务</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-ink-50 border-b border-ink-200">
              <tr>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">Job ID</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">状态</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">进度</th>
                <th className="text-left px-4 py-2.5 font-medium text-ink-500">创建时间</th>
                <th className="px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {btTasks.map((t) => (
                <tr key={t.job_id} className="border-b border-ink-100 hover:bg-ink-50">
                  <td className="px-4 py-2.5 font-mono text-xs">{t.job_id}</td>
                  <td className="px-4 py-2.5">
                    <span className={`quality-pill ${taskStatusColor(t.status)}`}>
                      {t.status}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{t.progress ?? 0}%</td>
                  <td className="px-4 py-2.5 text-xs text-ink-500">{t.created_at}</td>
                  <td className="px-4 py-2.5 text-right">
                    {t.status === "running" && (
                      <button className="text-rose-600 text-xs hover:underline" onClick={() => handleCancel(t.job_id)}>
                        取消
                      </button>
                    )}
                    {t.status === "done" && (
                      <button
                        className="text-brand-600 text-xs hover:underline"
                        onClick={() => setActiveJobId(t.job_id)}
                      >
                        查看结果
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function ResultCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="card-pad">
      <p className="label-muted">{label}</p>
      <p className="label-value mt-1">{value}</p>
    </div>
  );
}

function formatPct(v: number | undefined): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(2)}%`;
}

function formatNum(v: number | undefined): string {
  if (v == null) return "—";
  return v.toFixed(3);
}

function taskStatusColor(s: string): string {
  switch (s) {
    case "done": return "bg-emerald-100 text-emerald-700";
    case "failed": return "bg-rose-100 text-rose-700";
    case "running": return "bg-blue-100 text-blue-700";
    case "cancelled": return "bg-ink-100 text-ink-600";
    default: return "bg-amber-100 text-amber-700";
  }
}
