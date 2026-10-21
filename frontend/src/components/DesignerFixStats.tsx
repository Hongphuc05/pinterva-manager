import { useEffect, useState } from 'react'
import { AlertTriangle, ExternalLink, Loader2, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import { apiFetch, resolveAssetUrl } from '../api/client'

export type DesignerFixStat = {
  designer_id: string
  submitted_orders: number
  fixed_orders: number
  fix_rate: number
  fix_count: number
  max_fixes_per_order: number
  repeat_orders: number
  distribution: { '1': number; '2': number; '3+': number }
  excluded: { fake: number; admin_rejected: number }
}

type StatsResponse = { since: string; incomplete: boolean; repeat_threshold: number; designers: DesignerFixStat[] }

type FixedOrder = {
  order_id: string
  external_order_id: string
  product_name: string | null
  thumbnail_url: string | null
  first_submitted_at: string
  fix_count: number
  fixes: { at: string; reason: string | null; excluded: 'fake' | 'admin_rejected' | null }[]
}

export type FixRange = { from: string; to: string }

const EXCLUDED_LABEL = { fake: 'Fix giả (lỗi đồng bộ), không tính', admin_rejected: 'Admin đã từ chối, không tính' }

function isoDay(date: Date): string {
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return shifted.toISOString().slice(0, 10)
}

function rangeQuery(range: FixRange): string {
  const params = new URLSearchParams()
  if (range.from) params.set('date_from', range.from)
  if (range.to) params.set('date_to', range.to)
  const query = params.toString()
  return query ? `?${query}` : ''
}

function formatVn(iso: string): string {
  return new Date(iso).toLocaleString('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' })
}

/**
 * Admin: each Designer's Fix rate for the orders they first submitted in a period (default: the last 30
 * days). Fixes are credited to whoever made the submission QC answered; fake and Admin-rejected Fixes do
 * not count (see app/application/fix_stats.py).
 */
export function useDesignerFixStats(enabled: boolean) {
  const [range, setRange] = useState<FixRange>(() => {
    const today = new Date()
    return { from: isoDay(new Date(today.getTime() - 29 * 86400000)), to: isoDay(today) }
  })
  const [data, setData] = useState<StatsResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const invalid = Boolean(range.from && range.to && range.from > range.to)

  useEffect(() => {
    if (!enabled || invalid) return
    let alive = true
    setLoading(true)
    apiFetch<StatsResponse>(`/designers/fix-stats${rangeQuery(range)}`)
      .then((res) => alive && setData(res))
      .catch(() => alive && setData(null))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [enabled, invalid, range.from, range.to])

  const byDesigner = new Map((data?.designers ?? []).map((row) => [row.designer_id, row]))
  return { range, setRange, invalid, data, loading, byDesigner, threshold: data?.repeat_threshold ?? 3 }
}

export function FixStatsToolbar({ stats }: { stats: ReturnType<typeof useDesignerFixStats> }) {
  const { range, setRange, invalid, data, loading } = stats
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-orange-200 bg-orange-50/50 px-3 py-2 text-xs">
      <span className="font-bold text-orange-900">Tỷ lệ Fix theo ngày nộp bài lần đầu:</span>
      <label className="flex items-center gap-1 text-slate-600">
        Từ ngày
        <input type="date" aria-label="Fix từ ngày" value={range.from} max={range.to || undefined}
          onChange={(e) => setRange({ ...range, from: e.target.value })}
          className="rounded-lg border border-slate-300 bg-white px-1.5 py-1 text-xs" />
      </label>
      <label className="flex items-center gap-1 text-slate-600">
        đến ngày
        <input type="date" aria-label="Fix đến ngày" value={range.to} min={range.from || undefined}
          onChange={(e) => setRange({ ...range, to: e.target.value })}
          className="rounded-lg border border-slate-300 bg-white px-1.5 py-1 text-xs" />
      </label>
      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-orange-600" />}
      {invalid && <span className="text-red-700">Ngày bắt đầu phải trước ngày kết thúc.</span>}
      {data?.incomplete && !invalid && (
        <span className="text-amber-800">Dữ liệu Fix chỉ đầy đủ từ {new Date(data.since).toLocaleDateString('vi-VN')}.</span>
      )}
      <span className="text-slate-500">Không tính Fix giả và Fix bị Admin từ chối.</span>
    </div>
  )
}

export function FixStatsLine({ stat, threshold, onDetail }: { stat: DesignerFixStat | undefined; threshold: number; onDetail: () => void }) {
  if (!stat) return <div className="mt-1 text-[11px] text-slate-400">Fix: chưa có đơn nộp trong khoảng này</div>
  const tone = stat.fix_rate >= 30 ? 'text-red-700' : stat.fix_rate >= 15 ? 'text-orange-700' : 'text-emerald-700'
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px]">
      <span className="text-slate-600">
        Tỷ lệ Fix: <strong className={`font-mono ${tone}`}>{stat.fixed_orders}/{stat.submitted_orders} đơn ({stat.fix_rate}%)</strong>
        {stat.fix_count > stat.fixed_orders && <span className="text-slate-500"> · {stat.fix_count} lượt Fix</span>}
      </span>
      {stat.repeat_orders > 0 && (
        <span className="inline-flex items-center gap-1 rounded-md border border-red-200 bg-red-50 px-1.5 py-0.5 font-semibold text-red-700"
          title={`Có đơn bị Fix từ ${threshold} lần trở lên`}>
          <AlertTriangle className="h-3 w-3" />
          {stat.repeat_orders} đơn bị Fix ≥{threshold} lần (nhiều nhất {stat.max_fixes_per_order} lần)
        </span>
      )}
      {stat.fixed_orders + stat.excluded.fake + stat.excluded.admin_rejected > 0 && (
        <button type="button" onClick={(e) => { e.stopPropagation(); onDetail() }}
          className="rounded-md border border-slate-300 bg-white px-1.5 py-0.5 font-semibold text-[#0052CC] hover:bg-blue-50 cursor-pointer">
          Chi tiết Fix
        </button>
      )}
    </div>
  )
}

export function DesignerFixModal({ designerId, name, range, threshold, onClose }: {
  designerId: string
  name: string
  range: FixRange
  threshold: number
  onClose: () => void
}) {
  const [orders, setOrders] = useState<FixedOrder[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiFetch<{ orders: FixedOrder[] }>(`/designers/${designerId}/fix-stats${rangeQuery(range)}`)
      .then((res) => setOrders(res.orders))
      .catch((caught: any) => setError(caught?.message || 'Không tải được danh sách đơn.'))
  }, [designerId, range.from, range.to])

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div role="dialog" aria-label={`Đơn bị Fix của ${name}`} onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <div>
            <h3 className="text-sm font-bold text-slate-900">Đơn bị Fix của {name}</h3>
            <p className="text-[11px] text-slate-500">
              Đơn nộp lần đầu {range.from ? `từ ${new Date(range.from).toLocaleDateString('vi-VN')}` : ''}
              {range.to ? ` đến ${new Date(range.to).toLocaleDateString('vi-VN')}` : ''}, đơn bị Fix nhiều lần lên trước.
            </p>
          </div>
          <button type="button" aria-label="Đóng" onClick={onClose} className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 cursor-pointer">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="overflow-y-auto p-4 text-xs">
          {error && <p className="rounded bg-red-50 px-3 py-2 text-red-700">{error}</p>}
          {!orders && !error && (
            <p className="flex items-center gap-2 text-slate-500"><Loader2 className="h-4 w-4 animate-spin" /> Đang tải…</p>
          )}
          {orders && orders.length === 0 && <p className="text-slate-500">Không có đơn bị Fix trong khoảng này.</p>}
          <ul className="space-y-2">
            {orders?.map((order) => (
              <li key={order.order_id} className={`flex gap-3 rounded-xl border p-3 ${order.fix_count >= threshold ? 'border-red-200 bg-red-50/40' : 'border-slate-200'}`}>
                {order.thumbnail_url ? (
                  <img src={resolveAssetUrl(order.thumbnail_url)} alt="" loading="lazy" className="h-14 w-14 shrink-0 rounded-lg border border-slate-200 object-cover" />
                ) : (
                  <div className="h-14 w-14 shrink-0 rounded-lg bg-slate-100" />
                )}
                <div className="min-w-0 flex-1 space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-mono font-bold text-[#0052CC]">{order.external_order_id}</span>
                    <span className={`rounded-md px-1.5 py-0.5 font-bold ${order.fix_count >= threshold ? 'bg-red-600 text-white' : order.fix_count > 0 ? 'bg-orange-100 text-orange-800' : 'bg-slate-100 text-slate-600'}`}>
                      Fix {order.fix_count} lần
                    </span>
                    <Link to={`/orders/${order.order_id}`} className="inline-flex items-center gap-1 font-semibold text-[#0052CC] hover:underline">
                      Mở đơn <ExternalLink className="h-3 w-3" />
                    </Link>
                  </div>
                  <p className="truncate text-slate-700">{order.product_name}</p>
                  <p className="text-[11px] text-slate-500">Nộp lần đầu: {formatVn(order.first_submitted_at)}</p>
                  <ol className="space-y-0.5 text-[11px]">
                    {order.fixes.map((fix, index) => (
                      <li key={index} className={fix.excluded ? 'text-slate-400 line-through' : 'text-slate-700'}>
                        {formatVn(fix.at)}{fix.reason ? ` — ${fix.reason}` : ''}
                        {fix.excluded && <span className="ml-1 no-underline">({EXCLUDED_LABEL[fix.excluded]})</span>}
                      </li>
                    ))}
                  </ol>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
