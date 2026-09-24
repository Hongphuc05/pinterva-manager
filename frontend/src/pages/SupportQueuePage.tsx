import { useCallback, useEffect, useState } from 'react'
import { ChevronDown, ChevronRight, Cpu, ListChecks, Loader2, RefreshCw } from 'lucide-react'
import { DashboardLayout } from '../components/DashboardLayout'
import { fetchJobOrders, fetchQueue, type JobOrders, type QueueJob, type QueueOverview } from '../features/worker/queueApi'
import { useWorker } from '../features/worker/WorkerProvider'

const REFRESH_MS = 5000

function ago(iso: string | null): string {
  if (!iso) return ''
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (seconds < 60) return 'vừa xong'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} phút trước`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} giờ trước`
  return `${Math.floor(seconds / 86400)} ngày trước`
}

function MachineCard() {
  const { agent, probed, consent, busy, allow, stop } = useWorker()
  let title = 'Đang kiểm tra máy này…'
  let note = ''
  let action: { label: string; run: () => void; tone: 'primary' | 'plain' } | null = null

  if (probed && !agent) {
    title = 'Máy này chưa chạy agent'
    note = 'Bật agent trên máy này (docker compose up -d trong support_compare_image) để dùng GPU/CPU của máy chạy hàng đợi.'
  } else if (agent?.state === 'waiting') {
    title = consent === 'no' ? 'Bạn đã từ chối cho máy này chạy hàng đợi' : 'Máy này chưa được cho phép'
    note = 'Cho phép để hệ thống dùng GPU/CPU của máy này trong phiên đăng nhập hiện tại.'
    action = { label: 'Cho phép máy này', run: () => void allow(), tone: 'primary' }
  } else if (agent) {
    const running = agent.state === 'busy'
    title = running ? 'Máy này đang chạy hàng đợi' : agent.state === 'paused' ? 'Máy này tạm dừng' : 'Máy này sẵn sàng chạy hàng đợi'
    note =
      `${agent.name}${agent.device ? ` · ${agent.device.toUpperCase()}` : ''} · chỉ chạy trong phiên đăng nhập này.` +
      (agent.state === 'paused' ? ' Đang chờ kết nối lại với hệ thống.' : '')
    action = { label: 'Dừng máy này', run: () => void stop(), tone: 'plain' }
  }

  return (
    <div className="flex flex-col justify-between rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <div className={`rounded-lg p-2 shadow-sm ${agent && agent.state !== 'waiting' ? 'bg-emerald-600 text-white' : 'bg-slate-200 text-slate-600'}`}>
          <Cpu className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="text-sm font-bold text-slate-900">{title}</p>
          {note && <p className="mt-1 text-xs leading-relaxed text-slate-500">{note}</p>}
        </div>
      </div>
      {action && (
        <button
          type="button"
          disabled={busy}
          onClick={action.run}
          className={`mt-4 inline-flex w-fit items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-bold shadow-sm transition disabled:opacity-50 ${
            action.tone === 'primary' ? 'bg-blue-600 text-white hover:bg-blue-700' : 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
          }`}
        >
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {action.label}
        </button>
      )}
    </div>
  )
}

function JobRow({ job, index }: { job: QueueJob; index: number }) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<JobOrders | null>(null)
  const [error, setError] = useState(false)

  const load = useCallback(async () => {
    try {
      setDetail(await fetchJobOrders(job.id))
      setError(false)
    } catch {
      setError(true)
    }
  }, [job.id])

  useEffect(() => {
    if (!open) return
    void load()
    const timer = setInterval(() => void load(), REFRESH_MS)
    return () => clearInterval(timer)
  }, [open, load])

  const running = job.status === 'running'
  return (
    <li className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition hover:bg-slate-50"
      >
        {open ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
        <span className="grid size-7 place-items-center rounded-full bg-slate-100 text-xs font-bold text-slate-600">{index}</span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-semibold text-slate-900">
            {job.remaining_count} đơn chờ kiểm tra
            <span className="ml-2 text-xs font-medium text-slate-400">/ {job.requested_count} đơn của job</span>
          </span>
          <span className="block text-xs text-slate-500">
            {job.requested_by ? `${job.requested_by} · ` : ''}
            {ago(job.created_at)}
            {running && job.worker_name ? ` · máy ${job.worker_name}` : ''}
          </span>
        </span>
        <span
          className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ${
            running ? 'bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200' : 'bg-amber-50 text-amber-700 ring-1 ring-amber-200'
          }`}
        >
          {running ? 'Đang chạy' : 'Đang chờ'}
        </span>
      </button>
      {open && (
        <div className="border-t border-slate-100 px-4 py-3">
          {error ? (
            <p className="text-xs text-red-600">Không tải được danh sách đơn.</p>
          ) : !detail ? (
            <p className="flex items-center gap-2 text-xs text-slate-500"><Loader2 className="h-3.5 w-3.5 animate-spin" />Đang tải…</p>
          ) : detail.orders.length === 0 ? (
            <p className="text-xs text-slate-500">Không còn đơn nào chờ kiểm tra trong job này.</p>
          ) : (
            <ul className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {detail.orders.map((order) => (
                <li key={order.order_id} className="flex items-center gap-3 rounded-lg border border-slate-100 bg-slate-50 p-2">
                  {order.thumbnail_url ? (
                    <img src={order.thumbnail_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="size-10 flex-none rounded-md border border-slate-200 bg-white object-contain" />
                  ) : (
                    <span className="size-10 flex-none rounded-md border border-slate-200 bg-white" />
                  )}
                  <span className="min-w-0">
                    <span className="block font-mono text-xs font-semibold text-blue-700">{order.external_order_id}</span>
                    <span className="block truncate text-xs text-slate-500" title={order.product_name ?? ''}>{order.product_name ?? '—'}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  )
}

export function SupportQueuePage() {
  const [queue, setQueue] = useState<QueueOverview | null>(null)
  const [error, setError] = useState(false)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setQueue(await fetchQueue())
      setError(false)
    } catch {
      setError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  return (
    <DashboardLayout>
      <div className="mx-auto max-w-5xl space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-blue-600 p-2 text-white shadow-sm">
              <ListChecks className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-bold leading-tight text-slate-900">Hàng đợi kiểm tra trùng</h1>
              <p className="text-xs font-medium text-slate-500">Mỗi lần bấm “Có” trên Telegram là một job.</p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Làm mới
          </button>
        </div>

        <div className="grid gap-4 md:grid-cols-[minmax(0,220px)_1fr]">
          <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Job đang đợi</p>
            <p className="mt-2 text-5xl font-bold tabular-nums text-slate-900" data-testid="waiting-jobs">{queue?.waiting_jobs ?? '–'}</p>
          </div>
          <MachineCard />
        </div>

        {error && <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-xs font-medium text-red-700">Không tải được hàng đợi. Sẽ thử lại tự động.</div>}

        <section>
          <h2 className="mb-2 text-sm font-bold text-slate-800">Các job</h2>
          {!queue ? (
            <div className="flex items-center gap-2 py-8 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Đang tải…</div>
          ) : queue.jobs.length === 0 ? (
            <div className="rounded-xl border border-dashed border-slate-300 bg-white px-4 py-10 text-center text-sm text-slate-500">
              Không có job nào đang đợi.
            </div>
          ) : (
            <ul className="space-y-2">
              {queue.jobs.map((job, i) => (
                <JobRow key={job.id} job={job} index={i + 1} />
              ))}
            </ul>
          )}
        </section>
      </div>
    </DashboardLayout>
  )
}
