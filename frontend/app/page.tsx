import Link from "next/link";

export default function HomePage() {
  const tiles = [
    { href: "/dashboard", title: "市场概览工作台", desc: "KPI + 热图 + 多标的时间序列 + 交叉过滤", emoji: "📊" },
    { href: "/dashboard/replay", title: "历史回放", desc: "同一 PIT 查询逻辑,跨时点 replay", emoji: "⏪" },
    { href: "/panels/latest", title: "PIT Panel 研究台", desc: "宽表 + 因子对比 + 血缘跳转", emoji: "🔬" },
    { href: "/health", title: "数据源健康", desc: "Source Health Matrix + Revision Timeline", emoji: "❤️" },
    { href: "/findings/sample", title: "Finding 审计", desc: "完整 5 级血缘 + 证据卡片", emoji: "🧾" },
    { href: "/lineage/sample", title: "数据血缘图", desc: "Finding → Evidence → Feature → Obs → Raw", emoji: "🔗" },
    { href: "/reports/sample", title: "冻结报告", desc: "不可变 report + LLM Finding 列表", emoji: "📑" },
  ];
  return (
    <main className="min-h-screen bg-gradient-to-br from-ink-50 via-white to-brand-50/30">
      <header className="px-8 py-10 border-b border-ink-200 bg-white/60 backdrop-blur">
        <h1 className="text-3xl font-bold text-ink-900 tracking-tight">PIT Market Intelligence</h1>
        <p className="text-sm text-ink-500 mt-1.5 max-w-2xl">
          Auditable point-in-time data warehouse with evidence-traced LLM analysis.
          所有图表 / 表格 / KPI 严格使用后端 PIT 切片结果,前端不重算、不前向填充。
        </p>
        <div className="flex flex-wrap gap-2 mt-3 text-[11px] text-ink-500">
          <span className="badge bg-brand-50 text-brand-700">v1.0</span>
          <span className="badge bg-emerald-50 text-emerald-700">8 disciplines enforced</span>
          <span className="badge bg-amber-50 text-amber-700">14 PIT leakage cases verified</span>
          <span className="badge bg-ink-100 text-ink-700">346 backend tests</span>
        </div>
      </header>
      <section className="p-8 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 max-w-7xl mx-auto">
        {tiles.map((t) => (
          <Link
            key={t.href}
            href={t.href}
            className="card p-5 hover:shadow-md hover:border-brand-200 transition-all group"
          >
            <div className="text-2xl mb-2">{t.emoji}</div>
            <h2 className="text-sm font-semibold text-ink-900 mb-1 group-hover:text-brand-700">{t.title}</h2>
            <p className="text-xs text-ink-500">{t.desc}</p>
            <div className="mt-3 text-xs text-brand-600 font-mono">{t.href} →</div>
          </Link>
        ))}
      </section>
      <footer className="text-center text-xs text-ink-400 pb-8">
        <a href="https://github.com/raymodny-ai/PIT-Market-Intelligence-Platform" target="_blank" rel="noreferrer" className="hover:text-ink-700">
          github.com/raymodny-ai/PIT-Market-Intelligence-Platform
        </a>
      </footer>
    </main>
  );
}
