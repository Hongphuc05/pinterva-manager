import { useCallback, useEffect, useState } from 'react'
import { Loader2, Play, RefreshCw, Send, Workflow } from 'lucide-react'
import { ApiError } from '../../../api/client'
import { fetchCompareStatus, startCheck, startHandle, type CompareStatus } from '../../worker/compareApi'
import { fetchQueue, type QueueOverview } from '../../worker/queueApi'
import { AgentProgressPanel, Bar } from '../../worker/AgentProgressPanel'
import { useToast } from '../toast'

const REFRESH_MS = 4000

const HOST_LABEL: Record<string, string> = {
  busy: 'Đang chạy job',
  idle: 'Sẵn sàng',
  offline: 'Mất kết nối',
}

/** Run and watch the duplicate check from the web: the same two steps as Telegram /check and /handle. */
export function ControlView() {
  const toast = useToast()
  const [status, setStatus] = useState<CompareStatus | null>(null)
  const [queue, setQueue] = useState<QueueOverview | null>(null)
  const [busy, setBusy] = useState<'check' | 'handle' | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [s, q] = await Promise.all([fetchCompareStatus(), fetchQueue()])
      setStatus(s)
      setQueue(q)
    } catch {
      // the next refresh retries; a transient error must not blank the panel
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = setInterval(() => {
      if (!document.hidden) void load()
    }, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  const run = async (kind: 'check' | 'handle') => {
    if (!status || busy) return
    const question =
      kind === 'check'
        ? `Xếp ${status.new_orders} đơn mới vào hàng đợi kiểm tra trùng?`
        : `Chuyển ${status.handleable_orders} đơn đã so sánh mà không thấy trùng sang Không trùng lặp?`
    if (!window.confirm(question)) return
    setBusy(kind)
    try {
      if (kind === 'check') {
        const res = await startCheck()
        toast(`Đã xếp ${res.requested_count} đơn vào hàng đợi.`)
      } else {
        const res = await startHandle()
        toast(`Đã chuyển ${res.handled_count} đơn sang Không trùng lặp.`)
      }
      await load()
    } catch (e) {
      toast(e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setBusy(null)
    }
  }

  const hosts = queue?.hosts ?? []
  const jobs = queue?.jobs ?? []
  const disabled = !status?.enabled

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-bold text-slate-900">
          <Workflow className="h-4 w-4 text-blue-600" />Điều khiển và tiến độ
        </h2>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />Làm mới
        </button>
      </div>

      {status && !status.enabled && (
        <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-xs font-medium text-amber-800">
          Chức năng kiểm tra trùng đang tắt trên hệ thống.
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-bold text-slate-900">1. Kiểm tra trùng <span className="font-mono text-xs text-slate-400">/check</span></h3>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            Xếp các đơn ở tab Chưa kiểm tra chưa từng được so sánh vào một job; máy chạy agent sẽ embedding và so với pool.
          </p>
          <p className="mt-3 text-3xl font-bold tabular-nums text-slate-900" data-testid="new-orders">{status?.new_orders ?? '–'}</p>
          <button
            type="button"
            onClick={() => void run('check')}
            disabled={disabled || busy !== null || !status || status.new_orders === 0}
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3.5 py-1.5 text-xs font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:opacity-50"
          >
            {busy === 'check' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            Kiểm tra trùng
          </button>
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-sm font-bold text-slate-900">2. Chuyển không trùng <span className="font-mono text-xs text-slate-400">/handle</span></h3>
          <p className="mt-1 text-xs leading-relaxed text-slate-500">
            Chuyển các đơn đã so sánh mà không thấy trùng (hoặc bạn đã chọn Model sai) sang Không trùng lặp.
          </p>
          <p className="mt-3 text-3xl font-bold tabular-nums text-slate-900" data-testid="handleable-orders">{status?.handleable_orders ?? '–'}</p>
          <button
            type="button"
            onClick={() => void run('handle')}
            disabled={disabled || busy !== null || !status || status.handleable_orders === 0}
            className="mt-3 inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-bold text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50"
          >
            {busy === 'handle' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
            Chuyển sang Không trùng lặp
          </button>
        </section>
      </div>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" data-testid="control-hosts">
        <h3 className="text-sm font-bold text-slate-900">Máy chạy agent</h3>
        {hosts.length === 0 ? (
          <p className="mt-2 text-xs text-slate-500">Chưa có máy nào chạy agent. Job vẫn xếp hàng và sẽ chạy khi có máy.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {hosts.map((host) => (
              <li key={host.id} className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="text-sm font-semibold text-slate-900">{host.machine_name}</span>
                  <span className="text-xs font-bold text-slate-600">{HOST_LABEL[host.state] ?? host.state}</span>
                  <span className="text-xs text-slate-500">
                    Tài khoản {host.owner ?? '—'}
                    {host.device ? ` · ${host.device.toUpperCase()}` : ''}
                  </span>
                </div>
                <AgentProgressPanel progress={host.progress} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm" data-testid="control-jobs">
        <h3 className="text-sm font-bold text-slate-900">Job đang đợi và đang chạy</h3>
        {jobs.length === 0 ? (
          <p className="mt-2 text-xs text-slate-500">Không có job nào.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {jobs.map((job, index) => (
              <li key={job.id} className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                <div className="mb-1.5 flex items-center justify-between text-xs">
                  <span className="font-semibold text-slate-800">
                    Job {index + 1} · {job.requested_by ?? '—'}
                  </span>
                  <span className={job.status === 'running' ? 'font-bold text-emerald-700' : 'font-bold text-amber-700'}>
                    {job.status === 'running' ? `Đang chạy${job.worker_name ? ` trên ${job.worker_name}` : ''}` : 'Đang chờ máy'}
                  </span>
                </div>
                <Bar label="Đã so sánh" value={job.requested_count - job.remaining_count} total={job.requested_count} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
