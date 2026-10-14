import { useCallback, useEffect, useMemo, useState } from 'react'
import { Loader2, RefreshCw } from 'lucide-react'
import { fetchJob, fetchJobs, rejectItem, selectCandidate } from '../api'
import { canMarkModelWrong, canReview, lotName, TAB_OF, type Item, type Job, type TabKey } from '../types'
import { OrderCard } from '../components/OrderCard'
import { Empty, Loading } from '../components/Empty'
import { DetailModal } from '../components/DetailModal'
import { LinkRow } from '../components/LinkRow'
import { LotPanel } from '../components/LotPanel'
import { PairCard } from '../components/PairCard'
import { useToast } from '../toast'
import { STATUS } from './JobsView'

const TABS: { key: TabKey; label: string; hint: string }[] = [
  { key: 'todo', label: 'Cần duyệt', hint: 'Model nghi trùng, chưa chọn' },
  { key: 'pending', label: '1. Chờ xử lý', hint: 'Đã chọn ảnh trùng: gửi Telegram để verify' },
  { key: 'notdup', label: '2. Không trùng lặp', hint: 'Không thấy trùng, model sai hoặc bị từ chối' },
  { key: 'link', label: '3. Gắn link', hint: 'Đơn đã chuyển Trùng lặp: gắn link vào note làm việc' },
]

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

interface Props {
  jobId: string | null
  onJobChange: (jobId: string) => void
  onZoom: (src: string) => void
  zoomOpen: boolean
}

/** Left: the jobs to pick from. Right: the chosen job's orders, grouped in three tabs with counts. */
export function ReviewView({ jobId, onJobChange, onZoom, zoomOpen }: Props) {
  const toast = useToast()
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [tab, setTab] = useState<TabKey>('todo')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<Set<string>>(new Set())
  const [detail, setDetail] = useState<{ itemId: string; index: number } | null>(null)
  const [active, setActive] = useState(0)
  const [query, setQuery] = useState('')

  const loadJob = useCallback(async (id: string) => {
    try {
      const data = await fetchJob(id)
      setJob(data.job)
      setItems(data.items)
      setError(null)
    } catch (e) {
      setError(message(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadJobs = useCallback(async () => {
    try {
      const list = await fetchJobs()
      setJobs(list)
      return list
    } catch (e) {
      setError(message(e))
      setLoading(false)
      return null
    }
  }, [])

  // First load: the job list, then the requested (or newest) job.
  useEffect(() => {
    void (async () => {
      const list = await loadJobs()
      if (!list) return
      const id = (jobId && list.find((j) => j.id === jobId)?.id) || list[0]?.id
      if (id) {
        if (id !== jobId) onJobChange(id)
        await loadJob(id)
      } else {
        setLoading(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const choose = (id: string) => {
    setActive(0)
    setLoading(true)
    onJobChange(id)
    void loadJob(id)
  }

  // A running job fills in as the machine goes: refresh quietly until it completes.
  const running = job?.status === 'running'
  useEffect(() => {
    if (!running || !job) return
    const timer = setInterval(() => {
      if (!document.hidden) void loadJob(job.id)
    }, 8000)
    return () => clearInterval(timer)
  }, [running, job, loadJob])

  const groups = useMemo(
    () => {
      const by: Record<TabKey, Item[]> = { todo: [], pending: [], notdup: [], link: [] }
      for (const i of items) if (i.stage) by[TAB_OF[i.stage]].push(i)
      return by
    },
    [items],
  )
  const needle = query.trim().toLowerCase()
  const list = useMemo(
    () =>
      needle
        ? groups[tab].filter((i) => i.order_code.toLowerCase().includes(needle) || (i.product_name ?? '').toLowerCase().includes(needle))
        : groups[tab],
    [groups, tab, needle],
  )
  const current = list[Math.min(active, list.length - 1)]

  const act = useCallback(
    async (itemId: string, run: () => Promise<unknown>, success: string) => {
      setBusy((prev) => new Set(prev).add(itemId))
      try {
        await run()
        toast(success)
        if (job) await loadJob(job.id)
      } catch (e) {
        toast(message(e), 'error')
      } finally {
        setBusy((prev) => {
          const next = new Set(prev)
          next.delete(itemId)
          return next
        })
      }
    },
    [job, loadJob, toast],
  )

  const onSelect = useCallback(
    (itemId: string, candidateId: string) =>
      act(itemId, () => selectCandidate(itemId, candidateId), 'Đã chọn ảnh trùng. Vào tab Chờ xử lý để gửi cho Support hoặc Admin.'),
    [act],
  )
  const onReject = useCallback(
    (itemId: string) => act(itemId, () => rejectItem(itemId), 'Đã ghi nhận: model sai.'),
    [act],
  )

  // Keyboard: J/K move, 1-9/0 pick a candidate, D detail, X = model sai.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (e.metaKey || e.ctrlKey || e.altKey || zoomOpen || detail || ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return
      if (e.key === 'j' || e.key === 'ArrowDown') setActive((i) => Math.min(i + 1, Math.max(list.length - 1, 0)))
      else if (e.key === 'k' || e.key === 'ArrowUp') setActive((i) => Math.max(i - 1, 0))
      else if (current && !busy.has(current.id) && canReview(current)) {
        const n = e.key === '0' ? 10 : /^[1-9]$/.test(e.key) ? Number(e.key) : 0
        if (n && current.candidates[n - 1]) void onSelect(current.id, current.candidates[n - 1].id)
        else if (e.key === 'd') setDetail({ itemId: current.id, index: 0 })
        else if (e.key === 'x' && canMarkModelWrong(current)) void onReject(current.id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [list, current, busy, zoomOpen, detail, onSelect, onReject])

  useEffect(() => {
    if (current) document.querySelector(`[data-testid="order-${current.order_code}"]`)?.scrollIntoView?.({ block: 'nearest' })
  }, [current])

  const detailItem = detail && items.find((i) => i.id === detail.itemId)
  const pct = job && job.requested_count ? Math.min(100, Math.round((job.processed_count / job.requested_count) * 100)) : 0

  return (
    <div className="grid gap-4 lg:grid-cols-[264px_minmax(0,1fr)]">
      <aside className="lg:sticky lg:top-4 lg:self-start" aria-label="Danh sách job">
        <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2.5">
            <h2 className="text-xs font-bold uppercase tracking-wide text-slate-500">Job</h2>
            <button
              type="button"
              title="Tải lại"
              aria-label="Tải lại"
              onClick={() => void loadJobs().then(() => job && loadJob(job.id))}
              className="grid size-6 place-items-center rounded text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
            >
              <RefreshCw className="size-3.5" />
            </button>
          </div>
          {!jobs ? (
            <div className="flex justify-center py-6"><Loader2 className="size-4 animate-spin text-slate-400" /></div>
          ) : jobs.length === 0 ? (
            <p className="px-3 py-6 text-center text-xs text-slate-500">Chưa có job nào.</p>
          ) : (
            <ul className="max-h-[60vh] divide-y divide-slate-100 overflow-y-auto">
              {jobs.map((j) => {
                const status = STATUS[j.status] ?? STATUS.queued
                const selected = j.id === job?.id
                return (
                  <li key={j.id}>
                    <button
                      type="button"
                      aria-current={selected}
                      onClick={() => choose(j.id)}
                      className={`w-full px-3 py-2.5 text-left transition ${selected ? 'bg-blue-50/70' : 'hover:bg-slate-50'}`}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className={`text-[13px] font-semibold ${selected ? 'text-blue-700' : 'text-slate-800'}`}>{lotName(j)}</span>
                        <span className={`rounded-full px-2 py-px text-[10px] font-bold ring-1 ${status.tone}`}>{status.label}</span>
                      </span>
                      <span className="mt-0.5 block text-[11px] text-slate-500">
                        so sánh {j.processed_count}/{j.requested_count} · {j.duplicate_count} nghi trùng
                        {j.stages && ` · chờ xử lý ${j.stages.unsent + j.stages.waiting} · verify ${j.stages.verified + j.stages.linked}`}
                        {j.error_count > 0 && <b className="text-red-600"> · {j.error_count} lỗi</b>}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </aside>

      <section className="min-w-0">
        {job && (
          <div className="mb-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="text-sm font-bold text-slate-900">Lô {lotName(job)}</h2>
                <p className="text-xs text-slate-500">
                  {running ? <b className="text-blue-700">Đang chạy</b> : (STATUS[job.status]?.label ?? job.status)} · {job.processed_count}/{job.requested_count} đơn đã so
                  {job.error_count > 0 && <b className="text-red-600"> · {job.error_count} lỗi</b>}
                </p>
              </div>
              <span className="hidden text-[11px] text-slate-400 xl:block">
                <kbd className="font-mono">J</kbd>/<kbd className="font-mono">K</kbd> chuyển đơn · <kbd className="font-mono">1-9,0</kbd> chọn ảnh trùng · <kbd className="font-mono">D</kbd> chi tiết · <kbd className="font-mono">X</kbd> model sai
              </span>
            </div>
            {running && (
              <div className="mt-3 h-1.5 overflow-hidden rounded bg-slate-100" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                <div className="h-full bg-blue-600 transition-all" style={{ width: `${pct}%` }} />
              </div>
            )}
            <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4" role="tablist">
              {TABS.map(({ key, label, hint }) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  title={hint}
                  onClick={() => {
                    setTab(key)
                    setActive(0)
                  }}
                  className={`rounded-lg border px-3 py-2 text-left transition ${
                    tab === key ? 'border-blue-600 bg-blue-50 ring-1 ring-blue-600/20' : 'border-slate-200 bg-white hover:bg-slate-50'
                  }`}
                >
                  <span className={`block text-[11px] font-semibold ${tab === key ? 'text-blue-700' : 'text-slate-500'}`}>{label}</span>
                  <span className={`block font-mono text-lg font-bold tabular-nums ${tab === key ? 'text-blue-700' : 'text-slate-900'}`}>{groups[key].length}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {job && (
          <input
            type="search"
            aria-label="Lọc theo mã đơn hoặc tên"
            placeholder="Lọc theo mã đơn hoặc tên sản phẩm"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActive(0)
            }}
            className="mb-3 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs shadow-sm"
          />
        )}

        {job && (tab === 'pending' || tab === 'notdup') && (
          <LotPanel jobId={job.id} items={items} tab={tab} onChanged={() => loadJob(job.id)} />
        )}

        {loading ? (
          <Loading />
        ) : error ? (
          <Empty error title="Không tải được dữ liệu" note={error} />
        ) : !jobs?.length ? (
          <Empty title="Chưa có job nào" note="Bấm Kiểm tra trùng ở tab Điều khiển (hoặc /check trên Telegram) để tạo lô." />
        ) : list.length && tab === 'link' ? (
          list.map((item) => (
            <LinkRow key={item.id} item={item} onZoom={onZoom} onSaved={() => (job ? loadJob(job.id) : Promise.resolve())} />
          ))
        ) : list.length && tab === 'pending' ? (
          list.map((item) => (
            <PairCard
              key={item.id}
              item={item}
              onZoom={onZoom}
              busy={busy.has(item.id)}
              onReject={item.stage === 'unsent' ? onReject : undefined}
            />
          ))
        ) : list.length ? (
          list.map((item, idx) => (
            <OrderCard
              key={item.id}
              item={item}
              active={current?.id === item.id}
              busy={busy.has(item.id)}
              onSelect={onSelect}
              onReject={onReject}
              onZoom={onZoom}
              onFocus={() => setActive(idx)}
              onDetail={(itemId) => setDetail({ itemId, index: 0 })}
            />
          ))
        ) : (
          <Empty
            title="Không có đơn nào trong mục này"
            note={
              job?.status === 'queued'
                ? 'Job đang chờ một máy Support được cho phép nhận việc.'
                : tab === 'todo'
                  ? 'Bạn đã duyệt hết các đơn nghi trùng của job này.'
                  : undefined
            }
          />
        )}
      </section>

      {detail && detailItem ? (
        <DetailModal
          item={detailItem}
          index={Math.min(detail.index, detailItem.candidates.length - 1)}
          busy={busy.has(detailItem.id)}
          onIndex={(index) => setDetail({ itemId: detail.itemId, index })}
          onClose={() => setDetail(null)}
          onSelect={(itemId, candidateId) => {
            setDetail(null)
            void onSelect(itemId, candidateId)
          }}
        />
      ) : null}
    </div>
  )
}
