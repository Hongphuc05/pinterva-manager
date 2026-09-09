import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch, ApiError, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { getStatusInfo, getPrintervalStatusInfo } from '../utils/statusTranslation'
import { Package, RefreshCw, Radio, Loader2, UserPlus, X, User, AlertTriangle, Search, Filter } from 'lucide-react'

type OrderRow = {
  id: string
  external_order_id: string
  state: string
  product_name: string | null
  thumbnail_url: string | null
  assigned_designer_name: string | null
  printerval_status: string | null
  printerval_status_synced_at: string | null
  printerval_designer: string | null
  printerval_assignment_lifecycle: string | null
  printerval_assignment_error: string | null
}

type UserOption = {
  id: string
  username: string
  full_name: string
  role: string
}

// Once submitted, a Designer/Status change runs in the background (Playwright/HTTP
// write to Printerval) — poll a bit faster than the page's own idle refresh while any
// row is still "pending" so the per-row spinner actually clears once it lands, instead
// of only updating on the next manual/scheduled sync.
const PENDING_POLL_MS = 3000

export function OrderStatusPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [orders, setOrders] = useState<OrderRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const { status, triggerRun } = useSyncStatus()

  const [usersList, setUsersList] = useState<UserOption[]>([])
  const [printervalDesigners, setPrintervalDesigners] = useState<string[]>([])
  const [printervalStatuses, setPrintervalStatuses] = useState<string[]>([])
  const [loadingPrintervalOptions, setLoadingPrintervalOptions] = useState(false)

  const [selectedOrderIds, setSelectedOrderIds] = useState<string[]>([])
  const [bulkDesignerId, setBulkDesignerId] = useState('')
  const [bulkPrintervalDesigner, setBulkPrintervalDesigner] = useState('')
  const [bulkPrintervalStatus, setBulkPrintervalStatus] = useState('Doing')
  const [bulkApplying, setBulkApplying] = useState(false)

  const [searchQuery, setSearchQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [designerFilter, setDesignerFilter] = useState('')

  const [editingOrder, setEditingOrder] = useState<OrderRow | null>(null)
  const [editDesignerId, setEditDesignerId] = useState('')
  const [editPrintervalDesigner, setEditPrintervalDesigner] = useState('')
  const [editPrintervalStatus, setEditPrintervalStatus] = useState('Doing')
  const [applying, setApplying] = useState(false)

  // "Cập nhật toàn bộ" (refresh-detail) is synchronous on the backend (single order,
  // normally sub-second) — track per-row in-flight state purely client-side rather
  // than adding another lifecycle-tracked/polled system for one blocking call.
  const [refreshingDetailIds, setRefreshingDetailIds] = useState<Set<string>>(new Set())

  const pendingPollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

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
    if (isAdmin) {
      apiFetch<UserOption[]>('/users').then(setUsersList).catch(() => {})
    }
  }, [isAdmin])

  // Reload the table once a running sync finishes.
  useEffect(() => {
    if (status && !status.is_running) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status?.is_running])

  // Keep polling while any row's Printerval Designer/Status change is still in flight
  // ("pending") — otherwise the spinner would only ever clear on the next scheduled
  // mirror sync (up to 5 minutes later) or a manual page reload.
  useEffect(() => {
    const anyPending = orders.some((o) => o.printerval_assignment_lifecycle === 'pending')
    if (pendingPollRef.current) clearTimeout(pendingPollRef.current)
    if (anyPending) {
      pendingPollRef.current = setTimeout(load, PENDING_POLL_MS)
    }
    return () => {
      if (pendingPollRef.current) clearTimeout(pendingPollRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orders])

  async function loadPrintervalOptions(orderId: string) {
    setLoadingPrintervalOptions(true)
    try {
      const result = await apiFetch<{ designers: string[]; statuses: string[] }>(
        `/orders/${orderId}/printerval-options`
      )
      setPrintervalDesigners(result.designers)
      setPrintervalStatuses(result.statuses)
    } catch (err) {
      setPrintervalDesigners([])
      setPrintervalStatuses([])
      setError(err instanceof ApiError ? err.message : 'Không tải được danh sách Designer Printerval.')
    } finally {
      setLoadingPrintervalOptions(false)
    }
  }

  async function refreshPrintervalDesignerOptions() {
    setLoadingPrintervalOptions(true)
    try {
      const result = await apiFetch<{ designers: string[]; statuses: string[] }>(
        '/platforms/printerval-options/refresh',
        { method: 'POST' }
      )
      setPrintervalDesigners(result.designers)
      setPrintervalStatuses(result.statuses)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không cập nhật được Designer Printerval.')
    } finally {
      setLoadingPrintervalOptions(false)
    }
  }

  function openEdit(order: OrderRow) {
    setEditingOrder(order)
    setEditDesignerId('')
    setEditPrintervalDesigner(order.printerval_designer || '')
    setEditPrintervalStatus(order.printerval_status ? order.printerval_status[0].toUpperCase() + order.printerval_status.slice(1) : 'Doing')
    loadPrintervalOptions(order.id)
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
        (o.printerval_designer && o.printerval_designer.toLowerCase().includes(q))
      if (!matches) return false
    }

    if (statusFilter) {
      const pStatus = (o.printerval_status || '').toLowerCase()
      const target = statusFilter.toLowerCase()
      if (pStatus !== target && o.state.toLowerCase() !== target) return false
    }

    if (designerFilter) {
      if (designerFilter === 'unassigned') {
        if (o.assigned_designer_name || o.printerval_designer) return false
      } else {
        const desUser = usersList.find((u) => u.id === designerFilter)
        if (desUser) {
          const name = desUser.full_name || desUser.username
          if (o.assigned_designer_name !== name && o.printerval_designer !== name) return false
        }
      }
    }

    return true
  })

  function handleSelectAll(checked: boolean) {
    setSelectedOrderIds(checked ? filteredOrders.map((o) => o.id) : [])
  }

  useEffect(() => {
    const firstOrderId = selectedOrderIds[0]
    if (!firstOrderId) return
    setBulkPrintervalDesigner('')
    loadPrintervalOptions(firstOrderId)
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
    if (!editingOrder || !editPrintervalDesigner) return
    setApplying(true)
    try {
      await apiFetch(`/orders/${editingOrder.id}/printerval-assignment`, {
        method: 'POST',
        body: JSON.stringify({
          designer_id: editDesignerId || null,
          printerval_designer: editPrintervalDesigner,
          printerval_status: editPrintervalStatus,
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
    if (selectedOrderIds.length === 0 || !bulkPrintervalStatus) return
    setBulkApplying(true)
    try {
      const res = await apiFetch<{ queued_count: number }>('/orders/bulk-printerval-assignment', {
        method: 'POST',
        body: JSON.stringify({
          order_ids: selectedOrderIds,
          designer_id: bulkDesignerId || null,
          printerval_designer: bulkPrintervalDesigner || null,
          printerval_status: bulkPrintervalStatus,
        }),
      })
      setError(null)
      setSelectedOrderIds([])
      setBulkDesignerId('')
      setBulkPrintervalDesigner('')
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
            Trạng Thái Đơn — Mirror Từ Printerval
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Cột "Trạng thái Printerval" tự động đồng bộ theo lịch (mặc định mỗi 5 phút), hoặc bấm nút bên cạnh để đồng bộ ngay.
            {isAdmin && ' Admin có thể sửa Designer/Trạng thái Printerval trực tiếp từng đơn hoặc chọn nhiều đơn để sửa hàng loạt.'}
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
              onClick={refreshPrintervalDesignerOptions}
              disabled={loadingPrintervalOptions}
              className="px-3 py-1.5 text-xs font-bold text-white border border-white/40 rounded-lg hover:bg-white/10 disabled:opacity-60"
            >
              Cập nhật lựa chọn Printerval
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
              value={bulkPrintervalDesigner}
              onChange={(e) => setBulkPrintervalDesigner(e.target.value)}
              disabled={loadingPrintervalOptions}
              className="bg-white text-slate-800 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/30 focus:outline-none shadow-xs disabled:opacity-60"
            >
              <option value="">
                {loadingPrintervalOptions ? 'Đang tải DES Printerval...' : '-- Giữ nguyên DES / Chọn DES Printerval --'}
              </option>
              {printervalDesigners.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            <select
              value={bulkPrintervalStatus}
              onChange={(e) => setBulkPrintervalStatus(e.target.value)}
              disabled={loadingPrintervalOptions}
              className="bg-white text-slate-800 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/30 focus:outline-none shadow-xs disabled:opacity-60"
            >
              {(printervalStatuses.length ? printervalStatuses : ['Doing', 'Review', 'Fix', 'Done']).map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <button
              onClick={handleBulkApply}
              disabled={selectedOrderIds.length === 0 || !bulkPrintervalStatus || bulkApplying || loadingPrintervalOptions}
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
                      checked={filteredOrders.length > 0 && filteredOrders.every((o) => selectedOrderIds.includes(o.id))}
                      onChange={(e) => handleSelectAll(e.target.checked)}
                      className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] h-3.5 w-3.5 cursor-pointer"
                    />
                  </th>
                )}
                <th className="py-3 px-4 w-14 text-center">Ảnh</th>
                <th className="py-3 px-4">{isAdmin ? 'Mã Đơn' : 'Tên Đơn Hàng'}</th>
                <th className="py-3 px-4">Trạng Thái Nội Bộ</th>
                <th className="py-3 px-4">Trạng Thái Printerval</th>
                <th className="py-3 px-4">DES</th>
                <th className="py-3 px-4">Đồng bộ lúc</th>
                {isAdmin && <th className="py-3 px-4 text-right">Thao Tác</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs">
              {filteredOrders.length === 0 ? (
                <tr>
                  <td colSpan={isAdmin ? 8 : 6} className="py-12 text-center text-slate-400">
                    <Package className="h-10 w-10 mx-auto mb-2 opacity-30" />
                    <p className="font-medium text-sm text-slate-500">Không có đơn nào</p>
                  </td>
                </tr>
              ) : (
                filteredOrders.map((o) => {
                  const internal = getStatusInfo(o.state)
                  const site = getPrintervalStatusInfo(o.printerval_status)
                  const isPending = o.printerval_assignment_lifecycle === 'pending'
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
                            className="h-10 w-10 rounded-lg object-cover border border-slate-200 mx-auto"
                          />
                        ) : (
                          <div className="h-10 w-10 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
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
                            <Loader2 className="h-3.5 w-3.5 animate-spin text-[#0052CC]" aria-label="Đang đồng bộ Printerval" />
                          )}
                          {o.printerval_assignment_error && (
                            <span
                              className="cursor-help"
                              title={`Lần sửa gần nhất thất bại: ${o.printerval_assignment_error}`}
                            >
                              <AlertTriangle
                                className="h-3.5 w-3.5 text-red-600"
                                aria-label="Đồng bộ Printerval thất bại"
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
                            title="Click để sửa Designer/Trạng thái Printerval"
                          >
                            <User className="h-3 w-3" />
                            <span>{o.assigned_designer_name || '+ Phân công'}</span>
                          </span>
                        ) : (
                          o.assigned_designer_name || <span className="text-slate-300">-</span>
                        )}
                        {o.printerval_designer && (
                          <p className="mt-1 text-[10px] font-medium text-slate-500">
                            Printerval DES: {o.printerval_designer}
                          </p>
                        )}
                      </td>
                      <td className="py-2.5 px-4 font-mono text-slate-400">
                        {o.printerval_status_synced_at
                          ? new Date(o.printerval_status_synced_at).toLocaleString('vi-VN')
                          : '-'}
                      </td>
                      {isAdmin && (
                        <td className="py-2.5 px-4 text-right">
                          <div className="inline-flex items-center gap-1.5">
                            <button
                              onClick={() => handleRefreshDetail(o.id)}
                              disabled={refreshingDetailIds.has(o.id)}
                              title="Cập nhật toàn bộ thông tin đơn từ Printerval (template, ảnh nguồn, deadline...) — như Danh Sách Đơn Hàng"
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
                <h2 className="text-base font-bold text-slate-800">Sửa Designer / Trạng Thái Printerval</h2>
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
                  <option value="">-- Không chọn (chỉ sửa Printerval) --</option>
                  {usersList.map((u) => (
                    <option key={u.id} value={u.id}>{u.full_name || u.username} ({u.role})</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Designer trên Printerval <span className="text-red-500">*</span>
                </label>
                <button
                  type="button"
                  onClick={refreshPrintervalDesignerOptions}
                  disabled={loadingPrintervalOptions}
                  className="mb-1 text-[11px] font-semibold text-[#0052CC] hover:underline disabled:opacity-50"
                >
                  Cập nhật lựa chọn từ Printerval
                </button>
                <select
                  required
                  value={editPrintervalDesigner}
                  onChange={(e) => setEditPrintervalDesigner(e.target.value)}
                  disabled={loadingPrintervalOptions}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] disabled:bg-slate-100"
                >
                  <option value="">
                    {loadingPrintervalOptions ? 'Đang tải danh sách...' : '-- Chọn Designer Printerval --'}
                  </option>
                  {printervalDesigners.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Trạng thái trên Printerval <span className="text-red-500">*</span>
                </label>
                <select
                  required
                  value={editPrintervalStatus}
                  onChange={(e) => setEditPrintervalStatus(e.target.value)}
                  disabled={loadingPrintervalOptions}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] disabled:bg-slate-100"
                >
                  {(printervalStatuses.length ? printervalStatuses : ['Doing']).map((s) => <option key={s} value={s}>{s}</option>)}
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
                  disabled={applying || loadingPrintervalOptions || !editPrintervalDesigner}
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
