import type { AgentProgress } from './agentClient'

export function Bar({ label, value, total }: { label: string; value: number; total: number | null | undefined }) {
  const pct = total ? Math.min(100, Math.round((value / total) * 100)) : null
  return (
    <div>
      <div className="flex justify-between text-[11px] font-semibold text-slate-600">
        <span>{label}</span>
        <span className="tabular-nums">
          {value.toLocaleString('vi-VN')}
          {total ? ` / ${total.toLocaleString('vi-VN')} (${pct}%)` : ''}
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${pct ?? 0}%` }} />
      </div>
    </div>
  )
}

export function AgentProgressPanel({ progress }: { progress: AgentProgress | undefined }) {
  if (!progress || progress.phase === undefined || progress.phase === 'idle') return null
  const syncing = progress.phase === 'syncing_pool'
  return (
    <div className="mt-4 space-y-2.5 border-t border-slate-100 pt-3" data-testid="agent-progress">
      <p className="text-xs font-bold text-slate-800">
        {syncing ? 'Đang tải pool ảnh cũ về máy (chưa so sánh được)…' : 'Đang embedding và so sánh với pool'}
      </p>
      <Bar label="Pool trên máy" value={progress.pool_loaded ?? 0} total={progress.pool_total} />
      {progress.job_total ? (
        <>
          <Bar label="Embedding đơn mới" value={progress.job_embedded ?? 0} total={progress.job_total} />
          <Bar label="Đã so sánh và gửi kết quả" value={progress.job_compared ?? 0} total={progress.job_total} />
        </>
      ) : null}
    </div>
  )
}
