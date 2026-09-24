import { useCallback, useEffect, useMemo, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { fetchJob, fetchJobs, rejectItem, selectCandidate } from './api'
import { isDone, isNoMatch, isTodo, type Item, type Job, type TabKey } from './types'
import { Layout } from './components/Layout'
import { Kpis } from './components/Kpis'
import { OrderCard } from './components/OrderCard'
import { Empty, Loading } from './components/Empty'
import { Lightbox } from './components/Lightbox'
import { useToast } from './components/Toaster'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'todo', label: 'Cần duyệt' },
  { key: 'done', label: 'Đã duyệt' },
  { key: 'nomatch', label: 'Không thấy trùng' },
]

const jobLabel = (j: Job) =>
  `${j.created_at ? new Date(j.created_at).toLocaleString('vi-VN') : ''} · ${j.status} · ` +
  `${j.processed_count}/${j.requested_count} đơn · ${j.duplicate_count} nghi trùng`

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

  const loadJob = useCallback(async (id: string) => {
    if (!id) return
    setLoading(true)
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

  const groups = useMemo(
    () => ({
      todo: items.filter(isTodo),
      done: items.filter(isDone),
      nomatch: items.filter(isNoMatch),
    }),
    [items],
  )

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

  const onSelect = (itemId: string, candidateId: string) =>
    act(itemId, () => selectCandidate(itemId, candidateId), 'Đã chọn ảnh trùng. Telegram sẽ gửi cặp ảnh trong ≤60 giây.')
  const onReject = (itemId: string) => act(itemId, () => rejectItem(itemId), 'Đã ghi nhận: model sai.')

  const list = groups[tab]

  return (
    <Layout connected={connected}>
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Duyệt kết quả</h1>
        <p className="mt-1 max-w-3xl text-[13px] leading-relaxed text-muted-foreground">
          Mỗi ảnh đều kèm mã đơn. Chọn ảnh model gợi ý mà bạn thấy thật sự trùng để gửi Telegram xác nhận; nếu model
          sai, bấm "Model sai". Đơn "Model sai" và đơn không thấy trùng vẫn ở tab Chưa kiểm tra cho tới khi bạn gõ{' '}
          <span className="font-mono">/handle</span>.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        <label htmlFor="job" className="font-medium">Job</label>
        <select
          id="job"
          value={jobId}
          onChange={(e) => {
            setJobId(e.target.value)
            void loadJob(e.target.value)
          }}
          className="h-9 max-w-[340px] rounded-lg border border-border bg-white px-2.5 focus:outline-2 focus:outline-primary/35"
        >
          {jobs.map((j) => (
            <option key={j.id} value={j.id}>{jobLabel(j)}</option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void loadJobs()}
          className="inline-flex h-9 cursor-pointer items-center gap-1.5 rounded-md border border-border bg-white px-3.5 text-[13px] font-semibold transition hover:bg-tertiary"
        >
          <RefreshCw className="size-4" />Tải lại
        </button>
      </div>

      {job && <Kpis job={job} todo={groups.todo.length} done={groups.done.length} noMatch={groups.nomatch.length} />}

      <div className="flex flex-wrap gap-2" role="tablist">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`inline-flex cursor-pointer items-center gap-2 rounded-xl border px-3.5 py-2 text-xs font-bold transition ${
              tab === key
                ? 'border-primary bg-primary text-white ring-[3px] ring-primary/20'
                : 'border-border bg-white hover:bg-muted/50'
            }`}
          >
            {label}
            <span className={`rounded-full px-2 py-px font-mono text-[10px] ${tab === key ? 'bg-white/25' : 'bg-muted'}`}>
              {groups[key].length}
            </span>
          </button>
        ))}
      </div>

      <section>
        {loading ? (
          <Loading />
        ) : error ? (
          <Empty error title="Không tải được dữ liệu" note={error} />
        ) : !jobs.length ? (
          <Empty title="Chưa có job nào" note="Gõ /check trên Telegram rồi bấm Có để tạo job." />
        ) : list.length ? (
          list.map((item) => (
            <OrderCard key={item.id} item={item} busy={busy.has(item.id)} onSelect={onSelect} onReject={onReject} onZoom={setZoom} />
          ))
        ) : (
          <Empty
            title="Không có đơn nào trong mục này"
            note={tab === 'todo' ? 'Bạn đã duyệt hết các đơn nghi trùng của job này.' : undefined}
          />
        )}
      </section>
      <Lightbox src={zoom} onClose={() => setZoom(null)} />
    </Layout>
  )
}
