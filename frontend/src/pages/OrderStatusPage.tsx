import { useEffect, useState } from 'react'
import { apiFetch, ApiError } from '../api/client'
import { DashboardLayout } from '../components/DashboardLayout'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { getStatusInfo, getPrintervalStatusInfo } from '../utils/statusTranslation'
import { Package, RefreshCw, Radio } from 'lucide-react'

type OrderRow = {
  id: string
  external_order_id: string
  state: string
  product_name: string | null
  thumbnail_url: string | null
  assigned_designer_name: string | null
  printerval_status: string | null
  printerval_status_synced_at: string | null
}

export function OrderStatusPage() {
  const [orders, setOrders] = useState<OrderRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const { status, triggerRun } = useSyncStatus()

  async function load() {
    try {
      const data = await apiFetch<{ orders: OrderRow[] }>('/orders')
      setOrders(data.orders)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Không tải được danh sách đơn.')
    }
  }

  useEffect(() => {
    load()
  }, [])

  // Reload the table once a running sync finishes.
  useEffect(() => {
    if (status && !status.is_running) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.is_running])

  return (
    <DashboardLayout>
      <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-4 shadow-xs flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
            <Radio className="h-4 w-4 text-[#0052CC]" />
            Trạng Thái Đơn — Mirror Từ Printerval
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Chỉ xem, không ghi ngược lên Printerval. Cột "Trạng thái Printerval" tự động đồng bộ theo lịch (mặc định mỗi 5 phút), hoặc bấm nút bên cạnh để đồng bộ ngay.
            {status?.last_finished_at && (
              <span className="ml-1 text-slate-400">
                Lần đồng bộ gần nhất: {new Date(status.last_finished_at).toLocaleString('vi-VN')}
              </span>
            )}
          </p>
        </div>
        <button
          onClick={triggerRun}
          disabled={!!status?.is_running}
          className="inline-flex items-center gap-2 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl disabled:opacity-60 cursor-pointer shadow-2xs"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${status?.is_running ? 'animate-spin' : ''}`} />
          {status?.is_running ? 'Đang đồng bộ...' : 'Đồng bộ ngay'}
        </button>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-sm font-medium">
          {error}
        </div>
      )}

      <div className="rounded-xl border border-[hsl(var(--border))] bg-white shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500 tracking-wider">
                <th className="py-3 px-4 w-14 text-center">Ảnh</th>
                <th className="py-3 px-4">Mã Đơn</th>
                <th className="py-3 px-4">Trạng Thái Nội Bộ</th>
                <th className="py-3 px-4">Trạng Thái Printerval</th>
                <th className="py-3 px-4">DES</th>
                <th className="py-3 px-4">Đồng bộ lúc</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs">
              {orders.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-12 text-center text-slate-400">
                    <Package className="h-10 w-10 mx-auto mb-2 opacity-30" />
                    <p className="font-medium text-sm text-slate-500">Không có đơn nào</p>
                  </td>
                </tr>
              ) : (
                orders.map((o) => {
                  const internal = getStatusInfo(o.state)
                  const site = getPrintervalStatusInfo(o.printerval_status)
                  return (
                    <tr key={o.id} className="hover:bg-blue-50/40">
                      <td className="py-2.5 px-4 text-center">
                        {o.thumbnail_url ? (
                          <img
                            src={o.thumbnail_url}
                            alt={o.external_order_id}
                            className="h-10 w-10 rounded-lg object-cover border border-slate-200 mx-auto"
                          />
                        ) : (
                          <div className="h-10 w-10 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
                            <Package className="h-5 w-5" />
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 px-4 font-mono font-semibold text-[#0052CC]">
                        {o.external_order_id}
                      </td>
                      <td className="py-2.5 px-4">
                        <span
                          title={internal.description}
                          className={`inline-block px-2.5 py-1 text-[11px] font-semibold rounded-md border ${internal.badgeClass}`}
                        >
                          {internal.label}
                        </span>
                      </td>
                      <td className="py-2.5 px-4">
                        <span
                          title={site.description}
                          className={`inline-block px-2.5 py-1 text-[11px] font-semibold rounded-md border ${site.badgeClass}`}
                        >
                          {site.label}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-slate-600">
                        {o.assigned_designer_name || <span className="text-slate-300">-</span>}
                      </td>
                      <td className="py-2.5 px-4 font-mono text-slate-400">
                        {o.printerval_status_synced_at
                          ? new Date(o.printerval_status_synced_at).toLocaleString('vi-VN')
                          : '-'}
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </DashboardLayout>
  )
}
