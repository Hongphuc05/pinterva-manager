import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch, ApiError, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { Pagination, paginate } from '../components/Pagination'
import { getStatusInfo, getPlatformStatusInfo } from '../utils/statusTranslation'
import { Package, RefreshCw, Radio, Loader2, UserPlus, X, User, AlertTriangle, Search, Filter } from 'lucide-react'

type OrderRow = {
  id: string
  external_order_id: string
  state: string
  product_name: string | null
  thumbnail_url: string | null
  assigned_designer_name: string | null
  platform_status?: string | null
  platform_status_synced_at?: string | null
  platform_designer?: string | null
  platform_assignment_lifecycle?: string | null
  platform_assignment_error?: string | null
}

type UserOption = {
  id: string
  username: string
  full_name: string
  role: string
}

// Once submitted, a Designer/Status change runs in the background
// poll a bit faster than the page's own idle refresh while any
// row is still "pending" so the per-row spinner actually clears once it lands.
const PENDING_POLL_MS = 3000

export function OrderStatusPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [orders, setOrders] = useState<OrderRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const { status, triggerRun, isTriggering } = useSyncStatus()

  const [usersList, setUsersList] = useState<UserOption[]>([])
  const [platformDesigners, setPlatformDesigners] = useState<string[]>([])
  const [platformStatuses, setPlatformStatuses] = useState<string[]>([])
  const [loadingPlatformOptions, setLoadingPlatformOptions] = useState(false)

  const [selectedOrderIds, setSelectedOrderIds] = useState<string[]>([])
  const [bulkDesignerId, setBulkDesignerId] = useState('')
  const [bulkPlatformDesigner, setBulkPlatformDesigner] = useState('')
  const [bulkPlatformStatus, setBulkPlatformStatus] = useState('Doing')
  const [bulkApplying, setBulkApplying] = useState(false)

  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [designerFilter, setDesignerFilter] = useState('')
  const [currentPage, setCurrentPage] = useState(1)

  const [editingOrder, setEditingOrder] = useState<OrderRow | null>(null)
  const [editDesignerId, setEditDesignerId] = useState('')
  const [editPlatformDesigner, setEditPlatformDesigner] = useState('')
  const [editPlatformStatus, setEditPlatformStatus] = useState('Doing')
  const [applying, setApplying] = useState(false)

  // Track per-row in-flight state purely client-side
  const [refreshingDetailIds, setRefreshingDetailIds] = useState<Set<string>>(new Set())

  const pendingPollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  async function load() {
    try {
      const data = await apiFetch<{ orders: any[] }>('/orders')
      const mapped: OrderRow[] = (data.orders || []).map((o) => ({
        ...o,
        platform_status: o.platform_status || null,
        platform_status_synced_at: o.platform_status_synced_at || null,
        platform_designer: o.platform_designer || null,
        platform_assignment_lifecycle: o.platform_assignment_lifecycle || null,
        platform_assignment_error: o.platform_assignment_error || null,
      }))
      setOrders(mapped)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Không tải được danh sách đơn.')
    }
  }

  useEffect(() => {
    load()
    if (isAdmin) {
      apiFetch<UserOption[]>('/users').then(setUsersList).catch(() => {})
    }
  }, [isAdmin])

  // Reload the table once a running sync finishes.
  useEffect(() => {
    if (status && !status.is_running) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.is_running])

  // Keep polling while any row's Platform Designer/Status change is still in flight
  useEffect(() => {
    const anyPending = orders.some((o) => o.platform_assignment_lifecycle === 'pending')
    if (pendingPollRef.current) clearTimeout(pendingPollRef.current)
    if (anyPending) {
      pendingPollRef.current = setTimeout(load, PENDING_POLL_MS)
    }
    return () => {
      if (pendingPollRef.current) clearTimeout(pendingPollRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orders])

  async function loadPlatformOptions(orderId: string) {
    setLoadingPlatformOptions(true)
    try {
      const result = await apiFetch<{ designers: string[]; statuses: string[] }>(
        `/orders/${orderId}/platform-options`
      )
      setPlatformDesigners(result.designers)
      setPlatformStatuses(result.statuses)
    } catch (err) {
      setPlatformDesigners([])
      setPlatformStatuses([])
      setError(err instanceof ApiError ? err.message : 'Không tải được danh sách Designer trên hệ thống.')
    } finally {
      setLoadingPlatformOptions(false)
    }
  }

  async function refreshPlatformDesignerOptions() {
    setLoadingPlatformOptions(true)
    try {
      const result = await apiFetch<{ designers: string[]; statuses: string[] }>(
        '/platforms/platform-options/refresh',
        { method: 'POST' }
      )
      setPlatformDesigners(result.designers)
      setPlatformStatuses(result.statuses)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không cập nhật được Designer trên hệ thống.')
    } finally {
      setLoadingPlatformOptions(false)
    }
  }

  function openEdit(order: OrderRow) {
    setEditingOrder(order)
    setEditDesignerId('')
    setEditPlatformDesigner(order.platform_designer || '')
    const curStatus = order.platform_status
    setEditPlatformStatus(curStatus ? curStatus[0].toUpperCase() + curStatus.slice(1) : 'Doing')
    loadPlatformOptions(order.id)
  }

  function handleToggleSelect(orderId: string) {
    setSelectedOrderIds((prev) =>
      prev.includes(orderId) ? prev.filter((id) => id !== orderId) : [...prev, orderId]
    )
  }

  // Filter logic matching OrdersListPage
  const filteredOrders = orders.filter((o) => {
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      const matches =
        o.external_order_id.toLowerCase().includes(q) ||
        (o.product_name && o.product_name.toLowerCase().includes(q)) ||
        (o.assigned_designer_name && o.assigned_designer_name.toLowerCase().includes(q)) ||
        (o.platform_designer && o.platform_designer.toLowerCase().includes(q))
      if (!matches) return false
    }

    if (statusFilter) {
      const pStatus = (o.platform_status || '').toLowerCase()
      const target = statusFilter.toLowerCase()
      if (pStatus !== target && o.state.toLowerCase() !== target) return false
    }

    if (designerFilter) {
      if (designerFilter === 'unassigned') {
        if (o.assigned_designer_name || o.platform_designer) return false
      } else {
        const desUser = usersList.find((u) => u.id === designerFilter)
        if (desUser) {
          const name = desUser.full_name || desUser.username
          if (o.assigned_designer_name !== name && o.platform_designer !== name) return false
        }
      }
    }

    return true
  })

  // Reset page when filters change
  useEffect(() => {
    setCurrentPage(1)
  }, [searchQuery, statusFilter, designerFilter])

  const paginatedOrders = paginate(filteredOrders, currentPage)

  function handleSelectAll(checked: boolean) {
    setSelectedOrderIds(checked ? paginatedOrders.map((o) => o.id) : [])
  }

  useEffect(() => {
    const firstOrderId = selectedOrderIds[0]
    if (!firstOrderId) return
    setBulkPlatformDesigner('')
    loadPlatformOptions(firstOrderId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedOrderIds.length > 0 ? selectedOrderIds[0] : null])

  async function handleRefreshDetail(orderId: string) {
    setRefreshingDetailIds((prev) => new Set(prev).add(orderId))
    try {
      const res = await apiFetch<{ ok: boolean; message: string }>(
        `/orders/${orderId}/refresh-detail`,
        { method: 'POST' }
      )
      if (!res.ok) setError(res.message)
      else setError(null)
      load()
    } catch (err) {
      if (err instanceof ApiError) alert(`Lỗi cập nhật toàn bộ: ${err.message}`)
    } finally {
      setRefreshingDetailIds((prev) => {
        const next = new Set(prev)
        next.delete(orderId)
        return next
      })
    }
  }

  async function handleApplyEdit(e: React.FormEvent) {
    e.preventDefault()
    if (!editingOrder || !editPlatformDesigner) return
    setApplying(true)
    try {
      await apiFetch(`/orders/${editingOrder.id}/platform-assignment`, {
        method: 'POST',
        body: JSON.stringify({
          designer_id: editDesignerId || null,
          platform_designer: editPlatformDesigner,
          platform_status: editPlatformStatus,
        }),
      })
      setEditingOrder(null)
      load()
    } catch (err) {
      if (err instanceof ApiError) alert(`Lỗi cập nhật: ${err.message}`)
    } finally {
      setApplying(false)
    }
  }

  async function handleBulkApply() {
    if (selectedOrderIds.length === 0 || !bulkPlatformStatus) return
    setBulkApplying(true)
    try {
      const res = await apiFetch<{ queued_count: number }>('/orders/bulk-platform-assignment', {
        method: 'POST',
        body: JSON.stringify({
          order_ids: selectedOrderIds,
          designer_id: bulkDesignerId || null,
          platform_designer: bulkPlatformDesigner || null,
          platform_status: bulkPlatformStatus,
        }),
      })
      setError(null)
      setSelectedOrderIds([])
      setBulkDesignerId('')
      setBulkPlatformDesigner('')
      load()
      if (res.queued_count === 0) setError('Không có đơn nào được xếp đồng bộ.')
    } catch (err) {
      if (err instanceof ApiError) alert(`Lỗi cập nhật hàng loạt: ${err.message}`)
    } finally {
      setBulkApplying(false)
    }
  }

  return (
    <DashboardLayout>
      <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-4 shadow-xs flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-sm font-bold text-slate-800 flex items-center gap-2">
            <Radio className="h-4 w-4 text-[#0052CC]" />
            Trạng Thái Đơn — Mirror Từ Web Mẹ
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Cột "Trạng thái Web mẹ" tự động đồng bộ theo lịch (mặc định mỗi 5 phút), hoặc bấm nút bên cạnh để đồng bộ ngay.
            {isAdmin && ' Admin có thể sửa Designer/Trạng thái Web mẹ trực tiếp từng đơn hoặc chọn nhiều đơn để sửa hàng loạt.'}
            {status?.last_finished_at && (
              <span className="ml-1 text-slate-400">
                Lần đồng bộ gần nhất: {new Date(status.last_finished_at).toLocaleString('vi-VN')}
              </span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={async () => {
              try {
                await triggerRun()
              } catch (err: any) {
                setError(err?.message || 'Lỗi khi kích hoạt đồng bộ.')
              }
            }}
            disabled={isTriggering || !!status?.is_running}
            className="inline-flex items-center gap-2 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl disabled:opacity-60 cursor-pointer shadow-2xs transition-all"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${status?.is_running || isTriggering ? 'animate-spin' : ''}`} />
            {status?.is_running || isTriggering ? 'Đang đồng bộ...' : 'Đồng bộ ngay'}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-sm font-medium">
          {error}
        </div>
      )}

      {/* Filter Bar & Search */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-4 shadow-xs space-y-3">
        <div className="flex flex-col md:flex-row items-center justify-between gap-4 flex-wrap">
          {/* Search Box */}
          <div className="relative w-full md:w-72">
            <Search className="h-4 w-4 absolute left-3.5 top-3 text-slate-400" />
            <input
              type="text"
              placeholder={isAdmin ? "Tìm theo Mã Đơn, Tên SP, DES..." : "Tìm theo Tên Đơn, Tên SP..."}
              className="w-full pl-10 pr-4 py-2 text-xs rounded-lg border border-slate-200 focus:outline-none focus:border-[#0052CC] bg-slate-50"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2.5 w-full md:w-auto">
            <div className="flex items-center gap-1.5">
              <Filter className="h-3.5 w-3.5 text-slate-400" />
              <select
                className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC]"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="">Tất cả Trạng Thái</option>
                <option value="doing">Doing (Đang làm)</option>
                <option value="review">Review (Chờ duyệt)</option>
                <option value="fix">Fix (Cần sửa)</option>
                <option value="done">Done (Hoàn thành)</option>
                <option value="waiting">Waiting (Chờ làm)</option>
              </select>
            </div>

            {/* Filter by Designer (Admin only) */}
            {isAdmin && (
              <select
                className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC]"
                value={designerFilter}
                onChange={(e) => setDesignerFilter(e.target.value)}
              >
                <option value="">Tất cả DES</option>
                <option value="unassigned">Chưa phân công</option>
                {usersList.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.full_name || u.username} ({u.role})
                  </option>
                ))}
              </select>
            )}

            {(searchQuery || statusFilter || designerFilter) && (
              <button
                type="button"
                onClick={() => {
                  setSearchQuery('')
                  setStatusFilter('')
                  setDesignerFilter('')
                }}
                className="text-xs text-slate-500 hover:text-slate-800 underline font-medium cursor-pointer px-2"
              >
                Xóa bộ lọc
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Bulk Action Bar */}
      {isAdmin && selectedOrderIds.length > 0 && (
        <div className="bg-[#0052CC] text-white px-5 py-3 rounded-xl shadow-lg flex flex-wrap items-center justify-between gap-3 animate-in fade-in slide-in-from-top-2 border border-blue-400/30">
          <span className="bg-white/20 px-3 py-1 rounded-lg text-xs font-bold font-mono">
            Đã chọn {selectedOrderIds.length} đơn hàng
          </span>
          <div className="flex items-center gap-3 flex-wrap">
            <button
              type="button"
              onClick={refreshPlatformDesignerOptions}
              disabled={loadingPlatformOptions}
              className="px-3 py-1.5 text-xs font-bold text-white border border-white/40 rounded-lg hover:bg-white/10 disabled:opacity-60"
            >
              Cập nhật lựa chọn Web mẹ
            </button>
            <select
              value={bulkDesignerId}
              onChange={(e) => setBulkDesignerId(e.target.value)}
              className="bg-white text-slate-800 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/30 focus:outline-none shadow-xs"
            >
              <option value="">-- Designer nội bộ (không bắt buộc) --</option>
              {usersList.map((u) => (
                <option key={u.id} value={u.id}>{u.full_name || u.username} ({u.role})</option>
              ))}
            </select>
            <select
              value={bulkPlatformDesigner}
              onChange={(e) => setBulkPlatformDesigner(e.target.value)}
              disabled={loadingPlatformOptions}
              className="bg-white text-slate-800 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/30 focus:outline-none shadow-xs disabled:opacity-60"
            >
              <option value="">
                {loadingPlatformOptions ? 'Đang tải DES...' : '-- Giữ nguyên DES / Chọn DES Mẹ --'}
              </option>
              {platformDesigners.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            <select
              value={bulkPlatformStatus}
              onChange={(e) => setBulkPlatformStatus(e.target.value)}
              disabled={loadingPlatformOptions}
              className="bg-white text-slate-800 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/30 focus:outline-none shadow-xs disabled:opacity-60"
            >
              {(platformStatuses.length ? platformStatuses : ['Doing', 'Review', 'Fix', 'Done']).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <button
              onClick={handleBulkApply}
              disabled={selectedOrderIds.length === 0 || !bulkPlatformStatus || bulkApplying || loadingPlatformOptions}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-bold text-[#0052CC] bg-white hover:bg-slate-100 rounded-lg shadow-sm transition-all disabled:opacity-50 cursor-pointer"
            >
              {bulkApplying ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
              <span>Đổi Trạng Thái {selectedOrderIds.length} Đơn</span>
            </button>
            <button
              onClick={() => setSelectedOrderIds([])}
              className="text-xs text-white/80 hover:text-white underline px-2 cursor-pointer font-medium"
            >
              Bỏ chọn tất cả
            </button>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-[hsl(var(--border))] bg-white shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500 tracking-wider">
                {isAdmin && (
                  <th className="py-3 px-3 w-10 text-center">
                    <input
                      type="checkbox"
                      checked={paginatedOrders.length > 0 && paginatedOrders.every((o) => selectedOrderIds.includes(o.id))}
                      onChange={(e) => handleSelectAll(e.target.checked)}
                      className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] h-3.5 w-3.5 cursor-pointer"
                    />
                  </th>
                )}
                <th className="py-3 px-4 w-28 text-center">Ảnh</th>
                <th className="py-3 px-4">{isAdmin ? 'Mã Đơn' : 'Tên Đơn Hàng'}</th>
                <th className="py-3 px-4">Trạng Thái Nội Bộ</th>
                <th className="py-3 px-4">Trạng Thái Web Mẹ</th>
                <th className="py-3 px-4">DES</th>
                <th className="py-3 px-4">Đồng bộ lúc</th>
                {isAdmin && <th className="py-3 px-4 text-right">Thao Tác</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs">
              {paginatedOrders.length === 0 ? (
                <tr>
                  <td colSpan={isAdmin ? 8 : 6} className="py-12 text-center text-slate-400">
                    <Package className="h-10 w-10 mx-auto mb-2 opacity-30" />
                    <p className="font-medium text-sm text-slate-500">Không có đơn nào</p>
                  </td>
                </tr>
              ) : (
                paginatedOrders.map((o) => {
                  const internal = getStatusInfo(o.state)
                  const site = getPlatformStatusInfo(o.platform_status || null)
                  const isPending = o.platform_assignment_lifecycle === 'pending'
                  const isSelected = selectedOrderIds.includes(o.id)
                  return (
                    <tr key={o.id} className={`hover:bg-blue-50/40 ${isSelected ? 'bg-blue-50/60' : ''}`}>
                      {isAdmin && (
                        <td className="py-2.5 px-3 text-center">
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => handleToggleSelect(o.id)}
                            className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] h-3.5 w-3.5 cursor-pointer"
                          />
                        </td>
                      )}
                      <td className="py-2.5 px-4 text-center">
                        {o.thumbnail_url ? (
                          <img
                            src={resolveAssetUrl(o.thumbnail_url)}
                            alt={isAdmin ? o.external_order_id : (o.product_name || 'Đơn thiết kế')}
                            className="h-16 w-16 rounded-lg object-cover border border-slate-200 mx-auto"
                          />
                        ) : (
                          <div className="h-16 w-16 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
                            <Package className="h-5 w-5" />
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 px-4 font-semibold text-[#0052CC]">
                        {isAdmin ? (
                          <div>
                            <Link to={`/orders/${o.id}`} className="hover:underline font-mono">
                              {o.external_order_id}
                            </Link>
                            {o.product_name && (
                              <p className="text-[11px] text-slate-500 font-normal line-clamp-1 mt-0.5" title={o.product_name}>
                                {o.product_name}
                              </p>
                            )}
                          </div>
                        ) : (
                          <Link to={`/orders/${o.id}`} className="hover:underline line-clamp-2" title={o.product_name || 'Chi tiết đơn hàng'}>
                            {o.product_name || 'Đơn thiết kế'}
                          </Link>
                        )}
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
                        <span className="inline-flex items-center gap-1.5">
                          <span
                            title={site.description}
                            className={`inline-block px-2.5 py-1 text-[11px] font-semibold rounded-md border ${site.badgeClass}`}
                          >
                            {site.label}
                          </span>
                          {isPending && (
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-[#0052CC]" aria-label="Đang đồng bộ Web mẹ" />
                          )}
                          {o.platform_assignment_error && (
                            <span
                              className="cursor-help"
                              title={`Lần sửa gần nhất thất bại: ${o.platform_assignment_error}`}
                            >
                              <AlertTriangle
                                className="h-3.5 w-3.5 text-red-600"
                                aria-label="Đồng bộ Web mẹ thất bại"
                              />
                            </span>
                          )}
                        </span>
                      </td>
                      <td className="py-2.5 px-4 text-slate-600">
                        {isAdmin ? (
                          <span
                            onClick={() => openEdit(o)}
                            className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded font-semibold cursor-pointer transition-all hover:scale-105 ${
                              o.assigned_designer_name
                                ? 'bg-blue-50 text-[#0052CC] hover:bg-blue-100'
                                : 'bg-slate-50 text-slate-400 hover:text-[#0052CC] hover:bg-blue-50'
                            }`}
                            title="Click để sửa Designer/Trạng thái Web mẹ"
                          >
                            <User className="h-3 w-3" />
                            <span>{o.assigned_designer_name || '+ Phân công'}</span>
                          </span>
                        ) : (
                          o.assigned_designer_name || <span className="text-slate-300">-</span>
                        )}
                        {o.platform_designer && (
                          <p className="mt-1 text-[10px] font-medium text-slate-500">
                            Acc Mẹ DES: {o.platform_designer}
                          </p>
                        )}
                      </td>
                      <td className="py-2.5 px-4 font-mono text-slate-400">
                        {o.platform_status_synced_at
                          ? new Date(o.platform_status_synced_at).toLocaleString('vi-VN')
                          : '-'}
                      </td>
                      {isAdmin && (
                        <td className="py-2.5 px-4 text-right">
                          <div className="inline-flex items-center gap-1.5">
                            <button
                              onClick={() => handleRefreshDetail(o.id)}
                              disabled={refreshingDetailIds.has(o.id)}
                              title="Cập nhật toàn bộ thông tin đơn từ Web mẹ (SKU, ảnh nguồn, deadline...)"
                              className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors shadow-2xs cursor-pointer disabled:opacity-50"
                            >
                              <RefreshCw className={`h-3 w-3 ${refreshingDetailIds.has(o.id) ? 'animate-spin' : ''}`} />
                              <span>Cập nhật toàn bộ</span>
                            </button>
                            <button
                              onClick={() => openEdit(o)}
                              className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-lg transition-colors shadow-2xs cursor-pointer"
                            >
                              Sửa
                            </button>
                          </div>
                        </td>
                      )}
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <Pagination
          totalItems={filteredOrders.length}
          currentPage={currentPage}
          onPageChange={setCurrentPage}
        />
      </div>

      {/* Single-order edit modal */}
      {editingOrder && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
          onClick={() => setEditingOrder(null)}
        >
          <div
            className="relative w-full max-w-sm bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col border border-slate-200"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50">
              <div className="flex items-center gap-2">
                <UserPlus className="h-5 w-5 text-[#0052CC]" />
                <h2 className="text-base font-bold text-slate-800">Sửa Designer / Trạng Thái Web Mẹ</h2>
              </div>
              <button
                onClick={() => setEditingOrder(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleApplyEdit} className="p-6 space-y-4">
              <div className="text-xs space-y-1">
                <p className="text-slate-500 font-medium">
                  Đơn hàng: <strong className="text-slate-800 font-mono">{editingOrder.external_order_id}</strong>
                </p>
                {editingOrder.product_name && (
                  <p className="text-slate-600 line-clamp-1 font-semibold">{editingOrder.product_name}</p>
                )}
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Designer nội bộ (không bắt buộc — chỉ để lưu vết/phân công nội bộ)
                </label>
                <select
                  value={editDesignerId}
                  onChange={(e) => setEditDesignerId(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
                >
                  <option value="">-- Không chọn (chỉ sửa Web mẹ) --</option>
                  {usersList.map((u) => (
                    <option key={u.id} value={u.id}>{u.full_name || u.username} ({u.role})</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Designer trên Web Mẹ <span className="text-red-500">*</span>
                </label>
                <button
                  type="button"
                  onClick={refreshPlatformDesignerOptions}
                  disabled={loadingPlatformOptions}
                  className="mb-1 text-[11px] font-semibold text-[#0052CC] hover:underline disabled:opacity-50"
                >
                  Cập nhật lựa chọn từ Web mẹ
                </button>
                <select
                  required
                  value={editPlatformDesigner}
                  onChange={(e) => setEditPlatformDesigner(e.target.value)}
                  disabled={loadingPlatformOptions}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] disabled:bg-slate-100"
                >
                  <option value="">
                    {loadingPlatformOptions ? 'Đang tải danh sách...' : '-- Chọn Designer Web Mẹ --'}
                  </option>
                  {platformDesigners.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Trạng thái trên Web Mẹ <span className="text-red-500">*</span>
                </label>
                <select
                  required
                  value={editPlatformStatus}
                  onChange={(e) => setEditPlatformStatus(e.target.value)}
                  disabled={loadingPlatformOptions}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] disabled:bg-slate-100"
                >
                  {(platformStatuses.length ? platformStatuses : ['Doing']).map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>

              <div className="pt-3 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setEditingOrder(null)}
                  className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={applying || loadingPlatformOptions || !editPlatformDesigner}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl transition-colors shadow-2xs disabled:opacity-50 cursor-pointer"
                >
                  {applying && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>{applying ? 'Đang lưu...' : 'Xác Nhận'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </DashboardLayout>
  )
}
