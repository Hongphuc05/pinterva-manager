import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api/client'
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
  const [statusFilter, setStatusFilter] = useState('')
  const [flash, setFlash] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  async function loadOrders() {
    const params = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : ''
    const data = await apiFetch<{ orders: OrderSummary[] }>(`/orders${params}`)
    setOrders(data.orders)
  }

  useEffect(() => {
    loadOrders()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter])

  async function handleRefresh() {
    setRefreshing(true)
    try {
      const result = await apiFetch<{ flash: string }>('/orders/refresh', { method: 'POST' })
      setFlash(result.flash)
      await loadOrders()
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="p-6">
      <h1 className="text-xl font-bold mb-4">Đơn hàng</h1>
      {flash && <p className="mb-4 font-semibold">{flash}</p>}
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
      <select
        className="border p-1 mb-4"
        value={statusFilter}
        onChange={(e) => setStatusFilter(e.target.value)}
      >
        <option value="">Tất cả</option>
        <option value="DISCOVERED">DISCOVERED</option>
        <option value="CLAIMED_IMPORTED">CLAIMED_IMPORTED</option>
      </select>
      <table className="w-full border-collapse">
        <thead>
          <tr className="text-left border-b">
            <th>Ảnh</th>
            <th>Mã đơn</th>
            <th>SKU</th>
            <th>Trạng thái</th>
            <th>Deadline</th>
          </tr>
        </thead>
        <tbody>
          {orders.length === 0 && (
            <tr>
              <td colSpan={5}>Không có đơn nào.</td>
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
              <td>{o.deadline_at_ext ?? '-'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ponytail: status filter dropdown hard-codes 2 of the 10 OrderState values as a starting
// point (parity minimum) — a follow-up sub-project can fetch the full enum from the API if
// the dropdown needs to cover every state; not needed for this migration's parity goal.
