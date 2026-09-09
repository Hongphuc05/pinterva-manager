import { useEffect, useState, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { getStatusInfo } from '../utils/statusTranslation'
import { OrderHistoryTimelineModal } from '../components/OrderHistoryTimelineModal'
import {
  History,
  Search,
  Filter,
  RefreshCw,
  Clock,
  User,
  ExternalLink,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  AlertTriangle,
  Send,
  FileEdit,
  UserPlus,
  ArrowRight,
  Layers,
} from 'lucide-react'

export interface OrderHistoryItem {
  id: string
  created_at: string
  order_id: string
  external_order_id: string
  product_name: string | null
  thumbnail_url: string | null
  from_state: string | null
  to_state: string
  actor_id: string | null
  actor_name: string | null
  actor_role: string | null
  action: string | null
  description: string | null
  designer_name: string | null
  evidence: any
}

interface OrderHistoryResponse {
  items: OrderHistoryItem[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

type UserOption = {
  id: string
  username: string
  full_name: string
  role: string
}

export function OrderHistoryPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [historyItems, setHistoryItems] = useState<OrderHistoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Filters
  const [search, setSearch] = useState('')
  const [selectedDesignerId, setSelectedDesignerId] = useState('ALL')
  const [selectedAction, setSelectedAction] = useState('ALL')
  const [usersList, setUsersList] = useState<UserOption[]>([])

  // Modal timeline for a specific order
  const [selectedModalOrder, setSelectedModalOrder] = useState<{
    id: string
    external_order_id: string
    product_name?: string | null
  } | null>(null)

  // Load designers list if admin
  useEffect(() => {
    if (isAdmin) {
      apiFetch<UserOption[]>('/users')
        .then((res) => {
          setUsersList(res.filter((u) => u.role === 'designer'))
        })
        .catch(() => {})
    }
  }, [isAdmin])

  const fetchHistory = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      params.set('page', page.toString())
      params.set('page_size', '25')

      if (search.trim()) {
        params.set('search', search.trim())
      }
      if (selectedDesignerId && selectedDesignerId !== 'ALL') {
        params.set('designer_id', selectedDesignerId)
      }
      if (selectedAction && selectedAction !== 'ALL') {
        params.set('action', selectedAction)
      }

      const res = await apiFetch<OrderHistoryResponse>(`/orders-history?${params.toString()}`)
      setHistoryItems(res.items || [])
      setTotal(res.total || 0)
      setTotalPages(res.total_pages || 1)
    } catch (err: any) {
      setError(err.message || 'Không thể tải lịch sử hoạt động.')
    } finally {
      setLoading(false)
    }
  }, [page, search, selectedDesignerId, selectedAction])

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  function handleSearchSubmit(e: React.FormEvent) {
    e.preventDefault()
    setPage(1)
    fetchHistory()
  }

  function getActionBadge(item: OrderHistoryItem) {
    const act = (item.action || '').toUpperCase()
    if (act === 'APPROVE_DONE') {
      return {
        label: 'Duyệt Done',
        icon: CheckCircle2,
        color: 'text-emerald-700 bg-emerald-50 border-emerald-300',
        dot: 'bg-emerald-500',
      }
    }
    if (act === 'REQUEST_FIX') {
      return {
        label: 'Yêu Cầu Fix',
        icon: AlertTriangle,
        color: 'text-amber-700 bg-amber-50 border-amber-300',
        dot: 'bg-amber-500',
      }
    }
    if (act === 'SUBMIT_REVIEW') {
      return {
        label: 'Nộp Bài Review',
        icon: Send,
        color: 'text-purple-700 bg-purple-50 border-purple-300',
        dot: 'bg-purple-500',
      }
    }
    if (act === 'ASSIGN' || act === 'REASSIGN') {
      return {
        label: act === 'REASSIGN' ? 'Chia Lại Đơn' : 'Phân Công',
        icon: UserPlus,
        color: 'text-blue-700 bg-blue-50 border-blue-300',
        dot: 'bg-blue-500',
      }
    }
    if (act === 'START_DOING' || act === 'REVERT_TO_DOING') {
      return {
        label: act === 'REVERT_TO_DOING' ? 'Làm Lại Doing' : 'Bắt Đầu Làm',
        icon: FileEdit,
        color: 'text-indigo-700 bg-indigo-50 border-indigo-300',
        dot: 'bg-indigo-500',
      }
    }
    if (act === 'SET_WAITING') {
      return {
        label: 'Chờ Làm',
        icon: Clock,
        color: 'text-gray-700 bg-gray-50 border-gray-300',
        dot: 'bg-gray-400',
      }
    }
    return {
      label: 'Cập Nhật',
      icon: Clock,
      color: 'text-gray-700 bg-gray-50 border-gray-300',
      dot: 'bg-gray-400',
    }
  }

  function formatDateTime(isoStr: string) {
    try {
      const d = new Date(isoStr)
      return d.toLocaleString('vi-VN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
      })
    } catch {
      return isoStr
    }
  }

  return (
    <DashboardLayout>
      <div className="p-6 max-w-[1600px] mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-6 rounded-2xl shadow-sm border border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl bg-blue-50 border border-blue-100 flex items-center justify-center text-[#0052CC]">
              <History className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900 flex items-center gap-2">
                Lịch Sử Hoạt Động & Tiến Độ
                <span className="text-xs font-semibold px-2.5 py-0.5 rounded-full bg-blue-50 text-[#0052CC] border border-blue-200">
                  {total} sự kiện
                </span>
              </h1>
              <p className="text-sm text-gray-500 mt-0.5">
                Theo dõi chi tiết toàn bộ chu trình phân công, thay đổi trạng thái, nộp bài và duyệt đơn.
              </p>
            </div>
          </div>

          <button
            onClick={fetchHistory}
            disabled={loading}
            className="inline-flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-blue-600' : ''}`} />
            Làm mới
          </button>
        </div>

        {/* Filter Bar */}
        <div className="bg-white p-4 rounded-xl shadow-sm border border-gray-100 flex flex-wrap items-center gap-3">
          {/* Search */}
          <form onSubmit={handleSearchSubmit} className="flex-1 min-w-[280px]">
            <div className="relative">
              <Search className="w-4 h-4 text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                placeholder="Tìm theo mã đơn, tên sản phẩm, mô tả, tên người..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[#0052CC] focus:border-transparent"
              />
            </div>
          </form>

          {/* Action Type Filter */}
          <div className="flex items-center gap-2">
            <Filter className="w-4 h-4 text-gray-400" />
            <select
              value={selectedAction}
              onChange={(e) => {
                setSelectedAction(e.target.value)
                setPage(1)
              }}
              className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#0052CC]"
            >
              <option value="ALL">Tất cả hành động</option>
              <option value="ASSIGN">Phân công đơn</option>
              <option value="REASSIGN">Chia lại đơn</option>
              <option value="START_DOING">Bắt đầu làm (Doing)</option>
              <option value="SUBMIT_REVIEW">Nộp bài Review</option>
              <option value="APPROVE_DONE">Duyệt hoàn thành (Done)</option>
              <option value="REQUEST_FIX">Yêu cầu Fix</option>
              <option value="REVERT_TO_DOING">Làm lại Doing</option>
            </select>
          </div>

          {/* Designer Filter (for admin) */}
          {isAdmin && usersList.length > 0 && (
            <div className="flex items-center gap-2">
              <User className="w-4 h-4 text-gray-400" />
              <select
                value={selectedDesignerId}
                onChange={(e) => {
                  setSelectedDesignerId(e.target.value)
                  setPage(1)
                }}
                className="text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-[#0052CC]"
              >
                <option value="ALL">Tất cả Designer</option>
                {usersList.map((des) => (
                  <option key={des.id} value={des.id}>
                    {des.full_name || des.username}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-4 bg-red-50 border border-red-200 text-red-700 rounded-xl text-sm flex items-center gap-2">
            <AlertTriangle className="w-5 h-5 flex-shrink-0 text-red-500" />
            <span>{error}</span>
          </div>
        )}

        {/* Table / List */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-gray-50/75 border-b border-gray-100 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                <tr>
                  <th className="px-5 py-3.5">Thời Gian</th>
                  <th className="px-5 py-3.5">Đơn Hàng</th>
                  <th className="px-5 py-3.5">Hành Động</th>
                  <th className="px-5 py-3.5">Người Thực Hiện</th>
                  <th className="px-5 py-3.5">Luồng Trạng Thái</th>
                  <th className="px-5 py-3.5">Nội Dung Chi Tiết</th>
                  <th className="px-5 py-3.5 text-right">Xem</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading && historyItems.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-5 py-12 text-center text-gray-400">
                      <RefreshCw className="w-6 h-6 animate-spin mx-auto mb-2 text-[#0052CC]" />
                      Đang tải lịch sử hoạt động...
                    </td>
                  </tr>
                ) : historyItems.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-5 py-12 text-center text-gray-400">
                      Không tìm thấy bản ghi lịch sử nào phù hợp.
                    </td>
                  </tr>
                ) : (
                  historyItems.map((item) => {
                    const actionBadge = getActionBadge(item)
                    const ActionIcon = actionBadge.icon
                    const fromInfo = item.from_state ? getStatusInfo(item.from_state) : null
                    const toInfo = getStatusInfo(item.to_state)
                    const driveLink =
                      item.evidence?.drive_link ||
                      (item.evidence?.note?.includes('http') ? item.evidence.note : null)

                    return (
                      <tr key={item.id} className="hover:bg-gray-50/80 transition-colors">
                        {/* Timestamp */}
                        <td className="px-5 py-4 whitespace-nowrap text-xs text-gray-500 font-mono">
                          <div className="flex items-center gap-1.5">
                            <Clock className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
                            <span>{formatDateTime(item.created_at)}</span>
                          </div>
                        </td>

                        {/* Order Code & Thumbnail */}
                        <td className="px-5 py-4">
                          <div className="flex items-center gap-3">
                            {item.thumbnail_url ? (
                              <img
                                src={resolveAssetUrl(item.thumbnail_url)}
                                alt={item.external_order_id}
                                className="w-10 h-10 object-cover rounded-lg border border-gray-100 flex-shrink-0"
                              />
                            ) : (
                              <div className="w-10 h-10 rounded-lg bg-gray-100 border border-gray-200 flex items-center justify-center text-gray-400 flex-shrink-0">
                                <Layers className="w-5 h-5" />
                              </div>
                            )}
                            <div className="max-w-[200px]">
                              <Link
                                to={`/orders/${item.order_id}`}
                                className="font-bold text-gray-900 hover:text-[#0052CC] truncate block text-sm"
                                title={item.external_order_id}
                              >
                                #{item.external_order_id}
                              </Link>
                              {item.product_name && (
                                <p className="text-xs text-gray-400 truncate" title={item.product_name}>
                                  {item.product_name}
                                </p>
                              )}
                            </div>
                          </div>
                        </td>

                        {/* Action Badge */}
                        <td className="px-5 py-4 whitespace-nowrap">
                          <span
                            className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold border ${actionBadge.color}`}
                          >
                            <ActionIcon className="w-3.5 h-3.5" />
                            {actionBadge.label}
                          </span>
                        </td>

                        {/* Actor */}
                        <td className="px-5 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <div className="w-7 h-7 rounded-full bg-gray-100 border border-gray-200 flex items-center justify-center text-gray-600 font-bold text-xs">
                              {item.actor_name ? item.actor_name.charAt(0).toUpperCase() : '?'}
                            </div>
                            <div>
                              <div className="text-xs font-semibold text-gray-800">
                                {item.actor_name || 'Hệ thống'}
                              </div>
                              <span
                                className={`text-[10px] uppercase font-bold tracking-wider px-1.5 py-0.5 rounded ${
                                  item.actor_role === 'admin'
                                    ? 'bg-rose-50 text-rose-600 border border-rose-200'
                                    : 'bg-blue-50 text-blue-600 border border-blue-200'
                                }`}
                              >
                                {item.actor_role === 'admin' ? 'Admin' : 'Designer'}
                              </span>
                            </div>
                          </div>
                        </td>

                        {/* State Flow */}
                        <td className="px-5 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-1.5 text-xs">
                            {fromInfo ? (
                              <span
                                className={`px-2 py-0.5 rounded font-medium border ${fromInfo.badgeClass}`}
                              >
                                {fromInfo.label}
                              </span>
                            ) : (
                              <span className="px-2 py-0.5 rounded font-medium bg-gray-100 text-gray-500 border border-gray-200">
                                Mới
                              </span>
                            )}
                            <ArrowRight className="w-3.5 h-3.5 text-gray-400" />
                            <span
                              className={`px-2 py-0.5 rounded font-medium border ${toInfo.badgeClass}`}
                            >
                              {toInfo.label}
                            </span>
                          </div>
                        </td>

                        {/* Description & Evidence */}
                        <td className="px-5 py-4 max-w-[320px]">
                          <p className="text-xs text-gray-700 leading-relaxed break-words">
                            {item.description || 'Không có ghi chú thêm.'}
                          </p>
                          {item.designer_name && (
                            <div className="text-[11px] text-[#0052CC] mt-1 flex items-center gap-1">
                              <User className="w-3 h-3" />
                              <span>Designer: {item.designer_name}</span>
                            </div>
                          )}
                          {driveLink && (
                            <a
                              href={driveLink}
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-1 mt-1 text-xs text-[#0052CC] hover:text-blue-800 font-medium hover:underline"
                            >
                              <ExternalLink className="w-3 h-3" />
                              Link nộp bài Design
                            </a>
                          )}
                        </td>

                        {/* Quick view button */}
                        <td className="px-5 py-4 whitespace-nowrap text-right">
                          <button
                            onClick={() =>
                              setSelectedModalOrder({
                                id: item.order_id,
                                external_order_id: item.external_order_id,
                                product_name: item.product_name,
                              })
                            }
                            className="inline-flex items-center gap-1 px-2.5 py-1.5 text-xs font-medium text-[#0052CC] hover:text-blue-800 hover:bg-blue-50 rounded-lg transition-colors cursor-pointer"
                            title="Xem toàn bộ timeline của đơn này"
                          >
                            <History className="w-3.5 h-3.5" />
                            Timeline
                          </button>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination Bar */}
          {totalPages > 1 && (
            <div className="px-5 py-3.5 bg-gray-50/75 border-t border-gray-100 flex items-center justify-between text-xs text-gray-500">
              <div>
                Trang <span className="font-semibold text-gray-700">{page}</span> /{' '}
                <span className="font-semibold text-gray-700">{totalPages}</span> (Tổng {total} sự kiện)
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1 || loading}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                >
                  <ChevronLeft className="w-4 h-4" />
                  Trước
                </button>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages || loading}
                  className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-gray-200 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                >
                  Sau
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Order Timeline Modal */}
        {selectedModalOrder && (
          <OrderHistoryTimelineModal
            isOpen={!!selectedModalOrder}
            onClose={() => setSelectedModalOrder(null)}
            orderId={selectedModalOrder.id}
            externalOrderId={selectedModalOrder.external_order_id}
            productName={selectedModalOrder.product_name}
          />
        )}
      </div>
    </DashboardLayout>
  )
}
