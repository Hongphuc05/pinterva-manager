import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch, ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'

type OrderSummary = {
  id: string
  external_order_id: string
  state: string
  batch_id: string | null
  sku: string | null
  thumbnail_url: string | null
  deadline_at_ext: string | null
  created_at: string
}

export function OrdersListPage() {
  const { user } = useAuth()
  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [statusOptions, setStatusOptions] = useState<string[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [batchFilter, setBatchFilter] = useState('')
  const [flash, setFlash] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  async function loadOrders() {
    const params = new URLSearchParams()
    if (statusFilter) params.set('status', statusFilter)
    if (batchFilter) params.set('batch_id', batchFilter)
    const qs = params.toString()
    const data = await apiFetch<{ orders: OrderSummary[] }>(`/orders${qs ? `?${qs}` : ''}`)
    setOrders(data.orders)
  }

  useEffect(() => {
    apiFetch<{ states: string[] }>('/order-states')
      .then((r) => setStatusOptions(r.states))
      .catch(() => setStatusOptions([]))
  }, [])

  useEffect(() => {
    loadOrders().catch((e) => {
      setError(e instanceof ApiError ? e.message : 'Không tải được danh sách đơn.')
    })
  }, [statusFilter, batchFilter])

  async function handleRefresh() {
    setRefreshing(true)
    setError(null)
    try {
      const result = await apiFetch<{ flash: string }>('/orders/refresh', { method: 'POST' })
      setFlash(result.flash)
      await loadOrders()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Refresh thất bại.')
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-4">Đơn hàng</h1>
      {flash && <p className="mb-4 font-semibold">{flash}</p>}
      {error && <p className="mb-4 text-red-600">{error}</p>}
      {user?.role === 'admin' && (
        <div className="mb-4 space-x-4">
          <button
            className="bg-blue-600 text-white px-3 py-1 disabled:opacity-50"
            onClick={handleRefresh}
            disabled={refreshing}
          >
            {refreshing ? 'Đang crawl...' : 'Refresh'}
          </button>
          <Link className="underline" to="/printerval-login">
            Đăng nhập Printerval
          </Link>
        </div>
      )}
      <div className="mb-4 space-x-4">
        <select
          className="border p-1"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">Tất cả</option>
          {statusOptions.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {user?.role === 'admin' && (
          <input
            className="border p-1"
            placeholder="Batch ID"
            value={batchFilter}
            onChange={(e) => setBatchFilter(e.target.value)}
          />
        )}
      </div>
      <table className="w-full border-collapse">
        <thead>
          <tr className="text-left border-b">
            <th>Ảnh</th>
            <th>Mã đơn</th>
            <th>SKU</th>
            <th>Trạng thái</th>
            <th>Batch</th>
            <th>Deadline</th>
            <th>Ngày tạo</th>
          </tr>
        </thead>
        <tbody>
          {orders.length === 0 && (
            <tr>
              <td colSpan={7}>Không có đơn nào.</td>
            </tr>
          )}
          {orders.map((o) => (
            <tr key={o.id} className="border-b">
              <td>{o.thumbnail_url && <img src={o.thumbnail_url} alt="" className="h-10" />}</td>
              <td>
                <Link className="underline" to={`/orders/${o.id}`}>
                  {o.external_order_id}
                </Link>
              </td>
              <td>{o.sku ?? '-'}</td>
              <td>{o.state}</td>
              <td>{o.batch_id ?? '-'}</td>
              <td>{o.deadline_at_ext ?? '-'}</td>
              <td>{o.created_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
