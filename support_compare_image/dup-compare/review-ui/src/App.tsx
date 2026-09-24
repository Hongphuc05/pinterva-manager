import { useCallback, useEffect, useMemo, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { fetchJob, fetchJobs, rejectItem, selectCandidate } from './api'
import { isDone, isNoMatch, isSent, isTodo, type Item, type Job, type TabKey } from './types'
import { Layout, type View } from './components/Layout'
import { SearchPage } from './components/SearchPage'
import { OrderCard } from './components/OrderCard'
import { Empty, Loading } from './components/Empty'
import { Lightbox } from './components/Lightbox'
import { DetailModal } from './components/DetailModal'
import { useToast } from './components/Toaster'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'todo', label: 'Cần duyệt' },
  { key: 'done', label: 'Đã duyệt' },
  { key: 'nomatch', label: 'Không thấy trùng' },
]

const jobLabel = (j: Job) =>
  `${j.created_at ? new Date(j.created_at).toLocaleString('vi-VN') : ''} · ${j.status === 'running' ? 'đang chạy · ' : ''}${j.processed_count}/${j.requested_count} đơn · ${j.duplicate_count} nghi trùng`

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export default function App() {
  const toast = useToast()
  const [jobs, setJobs] = useState<Job[]>([])
  const [jobId, setJobId] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [tab, setTab] = useState<TabKey>('todo')
  const [connected, setConnected] = useState<boolean | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<Set<string>>(new Set())
  const [zoom, setZoom] = useState<string | null>(null)
  const [detail, setDetail] = useState<{ itemId: string; index: number } | null>(null)
  const [active, setActive] = useState(0)
  const [view, setView] = useState<View>(() => (window.location.hash === '#/search' ? 'search' : 'review'))

  const changeView = (next: View) => {
    setView(next)
    window.location.hash = next === 'search' ? '#/search' : '#/'
  }

  const loadJob = useCallback(async (id: string) => {
    if (!id) return
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
    setLoading(true)
    try {
      const list = await fetchJobs()
      setConnected(true)
      setJobs(list)
      const id = list[0]?.id ?? ''
      setJobId(id)
      if (id) await loadJob(id)
      else {
        setJob(null)
        setItems([])
        setLoading(false)
      }
    } catch (e) {
      setConnected(false)
      setError(message(e))
      setLoading(false)
    }
  }, [loadJob])

  useEffect(() => {
    void loadJobs()
  }, [loadJobs])

  // A running job fills in as the worker goes: refresh quietly until it completes.
  const running = job?.status === 'running'
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => void loadJob(jobId), 8000)
    return () => clearInterval(timer)
  }, [running, jobId, loadJob])

  const groups = useMemo(
    () => ({ todo: items.filter(isTodo), done: items.filter(isDone), nomatch: items.filter(isNoMatch) }),
    [items],
  )
  const list = groups[tab]
  const current = list[Math.min(active, list.length - 1)]

  const act = useCallback(
    async (itemId: string, run: () => Promise<unknown>, success: string) => {
      setBusy((prev) => new Set(prev).add(itemId))
      try {
        await run()
        toast(success)
        await loadJob(jobId)
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
    [jobId, loadJob, toast],
  )

  const onSelect = useCallback(
    (itemId: string, candidateId: string) =>
      act(itemId, () => selectCandidate(itemId, candidateId), 'Đã chọn ảnh trùng. Telegram gửi cặp ảnh trong ≤60 giây.'),
    [act],
  )
  const onReject = useCallback(
    (itemId: string) => act(itemId, () => rejectItem(itemId), 'Đã ghi nhận: model sai.'),
    [act],
  )

  // Keyboard: J/K move, 1-9 pick candidate, X = model sai, Esc closes the zoom.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (view !== 'review' || e.metaKey || e.ctrlKey || e.altKey || zoom || detail || ['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)) return
      if (e.key === 'j' || e.key === 'ArrowDown') setActive((i) => Math.min(i + 1, Math.max(list.length - 1, 0)))
      else if (e.key === 'k' || e.key === 'ArrowUp') setActive((i) => Math.max(i - 1, 0))
      else if (current && !busy.has(current.id) && !isSent(current) && (isTodo(current) || isDone(current))) {
        // 1-9 pick the 1st-9th candidate, 0 the 10th
        const n = e.key === '0' ? 10 : /^[1-9]$/.test(e.key) ? Number(e.key) : 0
        if (n && current.candidates[n - 1]) void onSelect(current.id, current.candidates[n - 1].id)
        else if (e.key === 'd') setDetail({ itemId: current.id, index: 0 })
        else if (e.key === 'x') void onReject(current.id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [view, list, current, busy, zoom, detail, onSelect, onReject])

  useEffect(() => {
    if (current) document.querySelector(`[data-testid="order-${current.order_code}"]`)?.scrollIntoView?.({ block: 'nearest' })
  }, [current])

  const switchTab = (key: TabKey) => {
    setTab(key)
    setActive(0)
  }

  const jobPicker = (
    <div className="flex items-center gap-1.5">
      <select
        aria-label="Job"
        value={jobId}
        onChange={(e) => {
          setJobId(e.target.value)
          setActive(0)
          void loadJob(e.target.value)
        }}
        className="h-7 max-w-[300px] rounded border border-line bg-surface px-2 text-xs outline-none focus:border-brand"
      >
        {jobs.map((j) => (
          <option key={j.id} value={j.id}>{jobLabel(j)}</option>
        ))}
      </select>
      <button
        type="button"
        title="Tải lại"
        aria-label="Tải lại"
        onClick={() => void loadJobs()}
        className="grid size-7 cursor-pointer place-items-center rounded border border-line bg-surface text-dim transition hover:text-fg"
      >
        <RefreshCw className="size-3.5" />
      </button>
    </div>
  )

  return (
    <Layout connected={connected} view={view} onView={changeView} right={view === 'review' ? jobPicker : undefined}>
      {view === 'search' ? (
        <SearchPage onZoom={setZoom} />
      ) : (
        <>
      <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex gap-1" role="tablist">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={tab === key}
              onClick={() => switchTab(key)}
              className={`inline-flex h-7 cursor-pointer items-center gap-1.5 rounded px-2.5 text-xs font-medium transition ${
                tab === key ? 'bg-raised text-fg' : 'text-dim hover:text-fg'
              }`}
            >
              {label}
              <span className={`font-mono text-[11px] ${tab === key ? 'text-brand' : ''}`}>{groups[key].length}</span>
            </button>
          ))}
        </div>
        {job && (
          <span className="text-xs text-dim">
            {running ? <b className="text-warn">Đang chạy</b> : `Job ${job.status}`} · {job.processed_count}/{job.requested_count} đơn đã so
            {job.error_count > 0 && <b className="text-bad"> · {job.error_count} lỗi</b>}
          </span>
        )}
        <span className="ml-auto hidden text-[11px] text-dim md:block">
          <kbd className="font-mono">J</kbd>/<kbd className="font-mono">K</kbd> chuyển đơn · <kbd className="font-mono">1-9,0</kbd> chọn ảnh trùng · <kbd className="font-mono">D</kbd> chi tiết ·{' '}
          <kbd className="font-mono">X</kbd> model sai
        </span>
      </div>

      {loading ? (
        <Loading />
      ) : error ? (
        <Empty error title="Không tải được dữ liệu" note={error} />
      ) : !jobs.length ? (
        <Empty title="Chưa có job nào" note="Gõ /check trên Telegram rồi bấm Có để tạo job." />
      ) : list.length ? (
        list.map((item, idx) => (
          <OrderCard
            key={item.id}
            item={item}
            active={current?.id === item.id}
            busy={busy.has(item.id)}
            onSelect={onSelect}
            onReject={onReject}
            onZoom={setZoom}
            onFocus={() => setActive(idx)}
            onDetail={(itemId) => setDetail({ itemId, index: 0 })}
          />
        ))
      ) : (
        <Empty
          title="Không có đơn nào trong mục này"
          note={tab === 'todo' ? 'Bạn đã duyệt hết các đơn nghi trùng của job này.' : undefined}
        />
      )}
        </>
      )}
      {(() => {
        const detailItem = detail && items.find((i) => i.id === detail.itemId)
        return detail && detailItem ? (
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
        ) : null
      })()}
      <Lightbox src={zoom} onClose={() => setZoom(null)} />
    </Layout>
  )
}
