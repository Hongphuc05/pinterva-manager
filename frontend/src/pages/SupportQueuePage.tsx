import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Cpu, Loader2, Power, X } from 'lucide-react'
import { DashboardLayout } from '../components/DashboardLayout'
import { useAuth } from '../auth/AuthContext'
import { approveDevice, cancelJob, fetchQueue, lookupDevice, revokeDevice } from '../features/dupReview/api'
import type { DeviceState, QueueJob, QueueState, WorkerDevice } from '../features/dupReview/types'
import { useToast } from '../features/dupReview/toast'

const REFRESH_MS = 5000

const DEVICE_LABEL: Record<DeviceState, { text: string; tone: string }> = {
  busy: { text: 'Đang chạy', tone: 'text-dup-warn' },
  idle: { text: 'Sẵn sàng', tone: 'text-dup-ok' },
  paused: { text: 'Tạm dừng (chưa có ai mở web)', tone: 'text-dup-dim' },
  offline: { text: 'Agent không phản hồi', tone: 'text-dup-bad' },
  revoked: { text: 'Đã thu hồi', tone: 'text-dup-dim' },
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

function ago(iso: string | null): string {
  if (!iso) return '—'
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000))
  if (seconds < 60) return `${seconds}s trước`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} phút trước`
  return `${Math.floor(seconds / 3600)} giờ trước`
}

function Section({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <section className="mb-5">
      <h2 className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
        {title}
        {count !== undefined && <span className="font-mono text-[11px] text-dup-brand">{count}</span>}
      </h2>
      {children}
    </section>
  )
}

const Empty = ({ children }: { children: ReactNode }) => (
  <div className="rounded-lg border border-dashed border-dup-line px-4 py-5 text-center text-xs text-dup-dim">{children}</div>
)

function Progress({ job }: { job: QueueJob }) {
  const pct = job.requested_count ? Math.min(100, Math.round((job.processed_count / job.requested_count) * 100)) : 0
  return (
    <div className="h-1.5 w-full overflow-hidden rounded bg-dup-raised" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-full bg-dup-brand transition-all" style={{ width: `${pct}%` }} />
    </div>
  )
}

function ConnectMachine({ onDone }: { onDone: () => void }) {
  const toast = useToast()
  const [params, setParams] = useSearchParams()
  const [code, setCode] = useState(params.get('code') ?? '')
  const [machine, setMachine] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const lookup = useCallback(
    async (value: string) => {
      setBusy(true)
      try {
        setMachine((await lookupDevice(value)).machine_name)
      } catch (e) {
        setMachine(null)
        toast(message(e), 'error')
      } finally {
        setBusy(false)
      }
    },
    [toast],
  )

  // Opening the link the agent printed (?code=...) shows the machine straight away.
  useEffect(() => {
    const preset = params.get('code')
    if (preset) void lookup(preset)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const reset = () => {
    setMachine(null)
    setCode('')
    const copy = new URLSearchParams(params)
    copy.delete('code')
    setParams(copy, { replace: true })
  }

  const allow = async () => {
    setBusy(true)
    try {
      await approveDevice(code)
      toast('Đã cho phép máy này chạy job. Giữ tab web này mở trong lúc máy làm việc.')
      reset()
      onDone()
    } catch (e) {
      toast(message(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-lg border border-dup-line bg-dup-surface p-3">
      {machine ? (
        <div className="flex flex-wrap items-center gap-3">
          <Cpu className="size-4 text-dup-brand" />
          <span>
            Máy <b>{machine}</b> muốn dùng <b>CPU/GPU</b> của nó để chạy job trong hàng đợi. Nó chỉ chạy khi bạn còn đăng nhập
            và mở web; đăng xuất hoặc đóng web thì máy tự dừng.
          </span>
          <div className="ml-auto flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void allow()}
              className="inline-flex h-7 cursor-pointer items-center gap-1.5 rounded bg-dup-brand px-3 text-xs font-medium text-white transition hover:brightness-110 disabled:opacity-50"
            >
              {busy && <Loader2 className="size-3.5 animate-spin" />}Cho phép
            </button>
            <button
              type="button"
              onClick={reset}
              className="h-7 cursor-pointer rounded border border-dup-line bg-dup-raised px-3 text-xs font-medium transition hover:text-dup-fg"
            >
              Không
            </button>
          </div>
        </div>
      ) : (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            if (code.trim()) void lookup(code)
          }}
        >
          <label htmlFor="device-code" className="text-xs text-dup-dim">Kết nối máy Support: nhập mã agent hiển thị</label>
          <input
            id="device-code"
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="ABCD-2345"
            maxLength={9}
            className="h-7 w-32 rounded border border-dup-line bg-dup-bg px-2 font-mono text-xs outline-none focus:border-dup-brand"
          />
          <button
            type="submit"
            disabled={busy || code.trim().length < 8}
            className="h-7 cursor-pointer rounded border border-dup-line bg-dup-raised px-3 text-xs font-medium transition hover:text-dup-fg disabled:opacity-50"
          >
            Kiểm tra mã
          </button>
        </form>
      )}
    </div>
  )
}

function DeviceRow({ device, canStop, onStop }: { device: WorkerDevice; canStop: boolean; onStop: () => void }) {
  const label = DEVICE_LABEL[device.state]
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg border border-dup-line bg-dup-surface px-3 py-2">
      <Cpu className="size-4 text-dup-dim" />
      <b>{device.machine_name}</b>
      <span className={`text-xs ${label.tone}`}>{label.text}</span>
      <span className="text-xs text-dup-dim">
        cho phép bởi {device.user_name ?? '—'} · agent {ago(device.last_seen_at)} · web {ago(device.presence_at)}
      </span>
      {canStop && (
        <button
          type="button"
          onClick={onStop}
          className="ml-auto inline-flex h-7 cursor-pointer items-center gap-1 rounded border border-dup-line bg-dup-raised px-2 text-xs transition hover:text-dup-bad"
        >
          <Power className="size-3" />Dừng máy
        </button>
      )}
    </li>
  )
}

function JobCard({ job, children }: { job: QueueJob; children?: ReactNode }) {
  return (
    <li className="rounded-lg border border-dup-line bg-dup-surface p-3">
      <div className="mb-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
        <Link to={`/duplicate-review?job=${job.id}`} className="font-mono font-medium text-dup-brand hover:underline">
          Job {job.id.slice(0, 8)}
        </Link>
        <span>{job.requested_count} đơn</span>
        {job.requested_by && <span className="text-dup-dim">yêu cầu bởi {job.requested_by}</span>}
        <span className="text-dup-dim">tạo {ago(job.created_at)}</span>
        {children}
      </div>
      {job.status === 'running' && (
        <>
          <Progress job={job} />
          <div className="mt-1.5 flex flex-wrap gap-x-4 text-[11px] text-dup-dim">
            <span>{job.processed_count}/{job.requested_count} đơn đã so</span>
            <span>{job.duplicate_count} nghi trùng</span>
            {job.error_count > 0 && <span className="text-dup-bad">{job.error_count} lỗi</span>}
            <span>máy: {job.worker_name ?? '—'}</span>
            <span>báo sống {ago(job.heartbeat_at)}</span>
          </div>
        </>
      )}
      {job.status === 'completed' && (
        <span className="text-[11px] text-dup-dim">
          Xong {ago(job.finished_at)} · {job.processed_count} đơn · {job.duplicate_count} nghi trùng
          {job.error_count > 0 && <b className="text-dup-bad"> · {job.error_count} lỗi</b>}
        </span>
      )}
      {job.status === 'failed' && <span className="text-[11px] text-dup-bad">Lỗi/hủy: {job.last_error ?? 'không rõ'}</span>}
    </li>
  )
}

export function SupportQueuePage() {
  const { user } = useAuth()
  const toast = useToast()
  const [queue, setQueue] = useState<QueueState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const isAdmin = user?.role === 'admin'

  const load = useCallback(async () => {
    try {
      setQueue(await fetchQueue())
      setError(null)
    } catch (e) {
      setError(message(e))
    }
  }, [])

  useEffect(() => {
    void load()
    const timer = setInterval(() => void load(), REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  const stop = async (device: WorkerDevice) => {
    try {
      await revokeDevice(device.id)
      toast(`Đã dừng máy ${device.machine_name}.`)
      await load()
    } catch (e) {
      toast(message(e), 'error')
    }
  }

  const cancel = async (job: QueueJob) => {
    if (!window.confirm(`Hủy job ${job.id.slice(0, 8)} (${job.requested_count} đơn)? Phải /check lại nếu muốn so sánh tiếp.`)) return
    try {
      await cancelJob(job.id)
      toast('Đã hủy job.')
      await load()
    } catch (e) {
      toast(message(e), 'error')
    }
  }

  const waiting = (queue?.queued.length ?? 0) + (queue?.running.length ?? 0) + (queue?.searches.filter((s) => s.status === 'queued').length ?? 0)
  const noMachine = queue !== null && queue.workers.ready === 0 && waiting > 0

  return (
    <DashboardLayout>
      <div className="min-h-[70vh] rounded-xl border border-dup-line bg-dup-bg p-4 text-[13px] text-dup-fg">
        <div className="mb-4 flex items-center gap-3">
          <b className="text-sm font-semibold">Hàng đợi so sánh</b>
          <Link to="/duplicate-review" className="ml-auto text-xs text-dup-dim hover:text-dup-fg">Duyệt trùng →</Link>
        </div>

        <div className="mb-4"><ConnectMachine onDone={() => void load()} /></div>

        {error && <div className="mb-4 rounded-lg border border-dup-bad/40 px-3 py-2 text-xs text-dup-bad">Không tải được hàng đợi: {error}</div>}
        {noMachine && (
          <div className="mb-4 rounded-lg border border-dup-warn/40 bg-dup-warn/10 px-3 py-2 text-xs text-dup-warn">
            Có việc đang chờ nhưng chưa có máy Support nào sẵn sàng. Chạy agent trên một máy, rồi nhập mã ở khung trên và bấm Cho phép.
            {queue.workers.paused > 0 && ' Máy đã kết nối đang tạm dừng vì chưa có ai mở web.'}
          </div>
        )}

        {!queue ? (
          <div className="flex items-center justify-center gap-2 py-12 text-dup-dim"><Loader2 className="size-4 animate-spin" />Đang tải…</div>
        ) : (
          <>
            <Section title="Máy Support đang kết nối" count={queue.workers.devices.length}>
              {queue.workers.devices.length ? (
                <ul className="space-y-2">
                  {queue.workers.devices.map((d) => (
                    <DeviceRow key={d.id} device={d} canStop={isAdmin || d.user_name === (user?.full_name || user?.username)} onStop={() => void stop(d)} />
                  ))}
                </ul>
              ) : (
                <Empty>Chưa có máy nào được cho phép.</Empty>
              )}
            </Section>

            <Section title="Đang chạy" count={queue.running.length}>
              {queue.running.length ? (
                <ul className="space-y-2">{queue.running.map((j) => <JobCard key={j.id} job={j} />)}</ul>
              ) : (
                <Empty>Không có job nào đang chạy.</Empty>
              )}
            </Section>

            <Section title="Đang chờ" count={queue.queued.length}>
              {queue.queued.length ? (
                <ul className="space-y-2">
                  {queue.queued.map((j) => (
                    <JobCard key={j.id} job={j}>
                      <span className="font-mono text-dup-warn">#{j.position}</span>
                      {isAdmin && (
                        <button
                          type="button"
                          onClick={() => void cancel(j)}
                          className="ml-auto inline-flex h-6 cursor-pointer items-center gap-1 rounded border border-dup-line bg-dup-raised px-2 text-[11px] transition hover:text-dup-bad"
                        >
                          <X className="size-3" />Hủy
                        </button>
                      )}
                    </JobCard>
                  ))}
                </ul>
              ) : (
                <Empty>Không có job nào đang chờ.</Empty>
              )}
            </Section>

            <Section title="Tìm ảnh" count={queue.searches.length}>
              {queue.searches.length ? (
                <ul className="space-y-1.5">
                  {queue.searches.map((s) => (
                    <li key={s.id} className="flex flex-wrap items-center gap-3 rounded border border-dup-line bg-dup-surface px-3 py-1.5 text-xs">
                      <span className="max-w-[240px] truncate font-medium" title={s.filename ?? ''}>{s.filename || 'Ảnh dán'}</span>
                      <span className={s.status === 'failed' ? 'text-dup-bad' : s.status === 'completed' ? 'text-dup-ok' : 'text-dup-warn'}>
                        {{ queued: 'đang chờ', running: 'đang xử lý', completed: 'xong', failed: 'lỗi' }[s.status] ?? s.status}
                      </span>
                      <span className="text-dup-dim">{s.requested_by ?? ''} · {ago(s.created_at)}</span>
                      {s.last_error && <span className="text-dup-bad">{s.last_error}</span>}
                    </li>
                  ))}
                </ul>
              ) : (
                <Empty>Chưa có yêu cầu tìm ảnh.</Empty>
              )}
            </Section>

            <Section title="Gần đây" count={queue.recent.length}>
              {queue.recent.length ? (
                <ul className="space-y-2">{queue.recent.map((j) => <JobCard key={j.id} job={j} />)}</ul>
              ) : (
                <Empty>Chưa có job nào kết thúc.</Empty>
              )}
            </Section>
          </>
        )}
      </div>
    </DashboardLayout>
  )
}
