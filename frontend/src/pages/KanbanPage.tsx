import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiFetch } from '../api/client'
import { DashboardLayout } from '../components/DashboardLayout'
import { Columns3, AlertTriangle, User, ChevronRight, Package } from 'lucide-react'

type Card = {
  id: string; external_order_id: string; state: string; product_name: string | null
  thumbnail_url: string | null; job_type: string | null; designer_name: string | null
  deadline_at_ext: string | null; alerts: string[]
}
type Column = { id: string; title: string; cards: Card[] }

export function KanbanPage() {
  const [columns, setColumns] = useState<Column[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    apiFetch<{ columns: Column[] }>('/kanban')
      .then((data) => {
        setColumns(data.columns)
        setError(null)
      })
      .catch((caught) => setError(caught instanceof ApiError ? caught.message : 'Không tải được dữ liệu Kanban.'))
      .finally(() => setLoading(false))
  }, [])

  function getStatusBadge(state: string) {
    switch (state) {
      case 'DONE':
      case 'CLAIMED_IMPORTED':
        return 'bg-emerald-100 text-emerald-800 border-emerald-200'
      case 'OPEN_FOR_ALLOCATION':
      case 'ASSIGNMENT_PENDING_APPROVAL':
      case 'QC_PENDING':
        return 'bg-amber-100 text-amber-800 border-amber-200'
      case 'IN_PROGRESS':
      case 'SUBMITTING_TO_SITE':
      case 'ASSIGNED':
        return 'bg-blue-100 text-blue-800 border-blue-200'
      case 'CANCELLED':
      case 'EXCEPTION':
        return 'bg-red-100 text-red-800 border-red-200'
      default:
        return 'bg-slate-100 text-slate-700 border-slate-200'
    }
  }

  return (
    <DashboardLayout>
      {/* Header Info Banner */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-bold text-slate-800 flex items-center gap-2">
            <Columns3 className="h-5 w-5 text-[#0052CC]" />
            <span>Bảng Tiến Độ Vận Hành (Ops Kanban Board)</span>
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">Theo dõi trực quan toàn bộ trạng thái vòng đời đơn hàng theo thời gian thực</p>
        </div>

        <div className="flex items-center gap-2 text-xs text-slate-500 bg-slate-50 px-3 py-1.5 rounded-lg border border-slate-200">
          <span className="font-semibold text-slate-700">Lưu ý:</span> Trạng thái chuyển dịch tự động theo quy trình State Machine.
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs font-semibold flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0 text-red-600" />
          <span>{error}</span>
        </div>
      )}

      {/* Kanban Columns */}
      {loading ? (
        <div className="flex gap-6 overflow-x-auto pb-4">
          {[1, 2, 3, 4].map((n) => (
            <div key={n} className="w-80 shrink-0 rounded-xl border border-slate-200 bg-white p-4 h-96 animate-pulse space-y-4">
              <div className="h-6 bg-slate-200 rounded-md w-3/4"></div>
              <div className="h-24 bg-slate-100 rounded-xl"></div>
              <div className="h-24 bg-slate-100 rounded-xl"></div>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex gap-6 overflow-x-auto pb-6">
          {columns.map((column) => (
            <section key={column.id} className="w-80 shrink-0 rounded-xl border border-slate-200 bg-slate-50/80 p-4 flex flex-col shadow-xs">
              {/* Column Title */}
              <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-200">
                <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">{column.title}</h3>
                <span className="font-mono text-xs font-bold px-2 py-0.5 rounded-full bg-white border border-slate-200 text-[#0052CC] shadow-2xs">
                  {column.cards.length}
                </span>
              </div>

              {/* Cards Container */}
              <div className="space-y-3 flex-1 min-h-[350px]">
                {column.cards.length === 0 ? (
                  <div className="h-full flex items-center justify-center p-6 text-center text-slate-400">
                    <p className="text-xs font-medium">Không có đơn ở cột này</p>
                  </div>
                ) : (
                  column.cards.map((card) => (
                    <Link
                      key={card.id}
                      to={`/orders/${card.id}`}
                      className="group block rounded-xl border border-slate-200 bg-white p-3.5 shadow-2xs hover:shadow-md hover:border-[#0052CC] transition-all space-y-2.5"
                    >
                      <div className="flex items-start gap-3">
                        {card.thumbnail_url ? (
                          <img src={card.thumbnail_url} alt="" className="h-12 w-12 rounded-lg object-cover border border-slate-200 shrink-0" />
                        ) : (
                          <div className="h-12 w-12 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                            <Package className="h-6 w-6" />
                          </div>
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between">
                            <span className="font-mono text-xs font-bold text-[#0052CC] group-hover:underline">
                              {card.external_order_id}
                            </span>
                            <ChevronRight className="h-3.5 w-3.5 text-slate-300 group-hover:text-[#0052CC] transition-colors" />
                          </div>
                          <p className="text-[11px] font-medium text-slate-600 truncate mt-0.5">
                            {card.product_name ?? card.job_type ?? 'Đơn 2D Custom'}
                          </p>
                        </div>
                      </div>

                      {/* Designer & State pills */}
                      <div className="flex items-center justify-between pt-2 border-t border-slate-100 text-[11px]">
                        <span className="flex items-center gap-1 text-slate-500 font-medium truncate max-w-[140px]">
                          <User className="h-3 w-3 text-slate-400" />
                          <span>{card.designer_name ?? 'Chưa gán'}</span>
                        </span>
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold border ${getStatusBadge(card.state)}`}>
                          {card.state}
                        </span>
                      </div>

                      {/* Alerts / Warnings */}
                      {card.alerts.length > 0 && (
                        <div className="flex flex-wrap gap-1 pt-1">
                          {card.alerts.map((alert) => (
                            <span key={alert} className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-red-50 text-red-700 border border-red-200 text-[10px] font-semibold">
                              <AlertTriangle className="h-3 w-3" />
                              <span>{alert}</span>
                            </span>
                          ))}
                        </div>
                      )}
                    </Link>
                  ))
                )}
              </div>
            </section>
          ))}
        </div>
      )}
    </DashboardLayout>
  )
}
