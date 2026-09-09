import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch, ApiError, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { ImageModal } from '../components/ImageModal'
import { TemplateModal, type TemplateJob } from '../components/TemplateModal'
import { StatusDropdown } from '../components/StatusDropdown'
import { STATE_MAP } from '../utils/statusTranslation'
import { 
  Package, 
  Search, 
  Filter, 
  RotateCcw, 
  Clock, 
  CheckCircle2, 
  Layers,
  ChevronRight,
  User,
  FileText,
  UserPlus,
  X,
  Loader2,
  ExternalLink,
  RefreshCw,
  AlertTriangle
} from 'lucide-react'

type OrderSummary = {
  id: string
  external_order_id: string
  state: string
  batch_id: string | null
  product_name: string | null
  sku: string | null
  thumbnail_url: string | null
  assigned_designer_name: string | null
  template_jobs: TemplateJob[] | null
  deadline_at_ext: string | null
  sku_image_url: string | null
  external_order_url: string | null
  source_files: { name: string; url: string }[] | null
  source_download_all_url: string | null
  printerval_designer: string | null
  printerval_status: string | null
  printerval_assignment_lifecycle: string | null
  created_at: string
  note_outsource?: string | null
  previous_note_outsource?: string | null
  fix_approved_by_admin?: boolean
}

type UserOption = {
  id: string
  username: string
  full_name: string
  role: string
}

export function OrdersListPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [statusOptions, setStatusOptions] = useState<string[]>([])
  const [statusFilter, setStatusFilter] = useState('')
  const [designerFilter, setDesignerFilter] = useState('')
  const [hasTemplateFilter, setHasTemplateFilter] = useState('')
  const [batchFilter, setBatchFilter] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [flash, setFlash] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeDesignerTab, setActiveDesignerTab] = useState<'todo' | 'doing' | 'review' | 'all'>('todo')
  const [syncingPrinterval, setSyncingPrinterval] = useState(false)

  // Highlight state for newly crawled jobs
  const [newlyCrawledOrderIds, setNewlyCrawledOrderIds] = useState<string[]>([])

  // Modals state
  const [selectedImage, setSelectedImage] = useState<string | null>(null)
  const [activeTemplateJobs, setActiveTemplateJobs] = useState<{ jobs: TemplateJob[]; orderId: string } | null>(null)

  // Assignment Modal state
  const [assigningOrder, setAssigningOrder] = useState<OrderSummary | null>(null)
  const [usersList, setUsersList] = useState<UserOption[]>([])
  const [selectedUserId, setSelectedUserId] = useState('')
  const [printervalDesigners, setPrintervalDesigners] = useState<string[]>([])
  const [printervalStatuses, setPrintervalStatuses] = useState<string[]>([])
  const [selectedPrintervalDesigner, setSelectedPrintervalDesigner] = useState('')
  const [selectedPrintervalStatus, setSelectedPrintervalStatus] = useState('Doing')
  const [loadingPrintervalOptions, setLoadingPrintervalOptions] = useState(false)
  const [assigning, setAssigning] = useState(false)

  // Bulk Selection State
  const [selectedOrderIds, setSelectedOrderIds] = useState<string[]>([])
  const [bulkDesignerId, setBulkDesignerId] = useState<string>('')
  const [bulkPrintervalDesigner, setBulkPrintervalDesigner] = useState('')
  const [bulkPrintervalStatus, setBulkPrintervalStatus] = useState('Doing')
  const [bulkAssigning, setBulkAssigning] = useState<boolean>(false)

  useEffect(() => {
    if (isAdmin) {
      apiFetch<UserOption[]>('/users').then(setUsersList).catch(() => {})
    }
  }, [isAdmin])

  useEffect(() => {
    if (!assigningOrder) return
    setSelectedUserId('')
    setSelectedPrintervalDesigner('')
    setSelectedPrintervalStatus('Doing')
    setLoadingPrintervalOptions(true)
    apiFetch<{ designers: string[]; statuses: string[] }>(
      `/orders/${assigningOrder.id}/printerval-options`
    )
      .then((result) => {
        setPrintervalDesigners(result.designers)
        setPrintervalStatuses(result.statuses)
      })
      .catch((err) => {
        setPrintervalDesigners([])
        setPrintervalStatuses([])
        setError(err instanceof ApiError ? err.message : 'Không tải được danh sách Designer Printerval.')
      })
      .finally(() => setLoadingPrintervalOptions(false))
  }, [assigningOrder])

  useEffect(() => {
    const firstOrderId = selectedOrderIds[0]
    if (!firstOrderId) {
      setBulkPrintervalDesigner('')
      return
    }
    setBulkPrintervalDesigner('')
    setLoadingPrintervalOptions(true)
    apiFetch<{ designers: string[]; statuses: string[] }>(
      `/orders/${firstOrderId}/printerval-options`
    )
      .then((result) => {
        setPrintervalDesigners(result.designers)
        setPrintervalStatuses(result.statuses)
      })
      .catch((err) => {
        setPrintervalDesigners([])
        setPrintervalStatuses([])
        setError(err instanceof ApiError ? err.message : 'Không tải được danh sách Designer Printerval.')
      })
      .finally(() => setLoadingPrintervalOptions(false))
  }, [selectedOrderIds])

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

  function dismissHighlight(orderId: string) {
    setNewlyCrawledOrderIds((prev) => prev.filter((id) => id !== orderId))
  }

  function handleSelectAll(checked: boolean) {
    if (checked) {
      setSelectedOrderIds(filteredOrders.map((o) => o.id))
    } else {
      setSelectedOrderIds([])
    }
  }

  function handleToggleSelect(orderId: string) {
    dismissHighlight(orderId)
    setSelectedOrderIds((prev) =>
      prev.includes(orderId) ? prev.filter((id) => id !== orderId) : [...prev, orderId]
    )
  }

  async function handleBulkAssign() {
    if (!bulkDesignerId || !bulkPrintervalDesigner || selectedOrderIds.length === 0) return
    setBulkAssigning(true)
    try {
      const res = await apiFetch<{ queued_count: number }>('/orders/bulk-printerval-assignment', {
        method: 'POST',
        body: JSON.stringify({
          order_ids: selectedOrderIds,
          designer_id: bulkDesignerId,
          printerval_designer: bulkPrintervalDesigner,
          printerval_status: bulkPrintervalStatus,
        }),
      })
      setFlash(`Đã phân công và xếp đồng bộ Printerval cho ${res.queued_count} đơn.`)
      selectedOrderIds.forEach(dismissHighlight)
      setSelectedOrderIds([])
      setBulkDesignerId('')
      setBulkPrintervalDesigner('')
      loadOrders()
    } catch (err) {
      if (err instanceof ApiError) {
        alert(`Lỗi phân công hàng loạt: ${err.message}`)
      }
    } finally {
      setBulkAssigning(false)
    }
  }

  async function handleAssignOrder(e: React.FormEvent) {
    e.preventDefault()
    if (!assigningOrder || !selectedUserId || !selectedPrintervalDesigner) return
    setAssigning(true)
    try {
      await apiFetch<{ request_id: string; lifecycle: string }>(
        `/orders/${assigningOrder.id}/printerval-assignment`,
        {
          method: 'POST',
          body: JSON.stringify({
            designer_id: selectedUserId,
            printerval_designer: selectedPrintervalDesigner,
            printerval_status: selectedPrintervalStatus,
          }),
        }
      )
      setFlash('Đã phân công và xếp đồng bộ Designer, trạng thái lên Printerval.')
      dismissHighlight(assigningOrder.id)
      setAssigningOrder(null)
      loadOrders()
    } catch (err) {
      if (err instanceof ApiError) {
        alert(`Lỗi phân công: ${err.message}`)
      }
    } finally {
      setAssigning(false)
    }
  }

  async function loadOrders() {
    const params = new URLSearchParams()
    if (statusFilter) params.set('status', statusFilter)
    if (batchFilter) params.set('batch_id', batchFilter)
    if (designerFilter && designerFilter !== 'unassigned') params.set('designer_id', designerFilter)
    if (designerFilter === 'unassigned') params.set('designer_id', 'unassigned')
    const qs = params.toString()
    const data = await apiFetch<{ orders: OrderSummary[] }>(`/orders${qs ? `?${qs}` : ''}`)
    
    // Detect newly arrived orders
    setOrders((prevOrders) => {
      if (prevOrders.length > 0) {
        const existingIds = new Set(prevOrders.map((o) => o.id))
        const newIds = data.orders.filter((o) => !existingIds.has(o.id)).map((o) => o.id)
        if (newIds.length > 0) {
          setNewlyCrawledOrderIds((prev) => Array.from(new Set([...prev, ...newIds])))
          // Auto-remove highlights after 3 minutes (180,000ms)
          setTimeout(() => {
            setNewlyCrawledOrderIds((prev) => prev.filter((id) => !newIds.includes(id)))
          }, 180000)
        }
      }
      return data.orders
    })
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

    function handleOrdersUpdated() {
      loadOrders().catch(() => {})
    }
    window.addEventListener('orders-updated', handleOrdersUpdated)
    return () => window.removeEventListener('orders-updated', handleOrdersUpdated)
  }, [statusFilter, batchFilter, designerFilter])

  async function handleSyncPrintervalStatus(orderIds?: string[]) {
    setSyncingPrinterval(true)
    window.dispatchEvent(new CustomEvent('sync-printerval-start'))
    try {
      const res = await apiFetch<{ synced_count: number; updated_count: number; message: string }>(
        '/orders/sync-printerval-status',
        {
          method: 'POST',
          body: JSON.stringify(orderIds && orderIds.length > 0 ? { order_ids: orderIds } : {}),
        }
      )
      await loadOrders()
      setFlash(res.message || 'Đã đồng bộ trạng thái đơn từ Printerval.')
    } catch (err: any) {
      setError(err?.message || 'Lỗi khi đồng bộ từ Printerval.')
    } finally {
      setSyncingPrinterval(false)
      window.dispatchEvent(new CustomEvent('sync-printerval-end'))
    }
  }

  // Calculate Designer Workflow groups
  const todoOrders = orders.filter(
    (o) =>
      ['WAITING', 'ASSIGNED', 'OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING'].includes(o.state.toUpperCase()) ||
      (['REVISION', 'REVISION_REQUESTED'].includes(o.state.toUpperCase()) && o.fix_approved_by_admin)
  )
  const doingOrders = orders.filter((o) => ['IN_PROGRESS'].includes(o.state.toUpperCase()))
  const reviewOrders = orders.filter((o) =>
    ['QC_PENDING', 'RESULT_SUBMITTED', 'SUBMITTING_TO_SITE'].includes(o.state.toUpperCase())
  )

  const baseOrders = !isAdmin
    ? activeDesignerTab === 'todo'
      ? todoOrders
      : activeDesignerTab === 'doing'
      ? doingOrders
      : activeDesignerTab === 'review'
      ? reviewOrders
      : orders
    : orders

  // Filter client-side search & template filters
  const filteredOrders = baseOrders.filter((o) => {
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      const matches =
        o.external_order_id.toLowerCase().includes(q) ||
        (o.product_name && o.product_name.toLowerCase().includes(q)) ||
        (o.assigned_designer_name && o.assigned_designer_name.toLowerCase().includes(q))
      if (!matches) return false
    }

    if (designerFilter) {
      if (designerFilter === 'unassigned') {
        if (o.assigned_designer_name) return false
      } else {
        const desUser = usersList.find((u) => u.id === designerFilter)
        if (desUser) {
          const name = desUser.full_name || desUser.username
          if (o.assigned_designer_name !== name) return false
        }
      }
    }

    if (hasTemplateFilter) {
      const hasT = o.template_jobs && o.template_jobs.length > 0
      if (hasTemplateFilter === 'yes' && !hasT) return false
      if (hasTemplateFilter === 'no' && hasT) return false
    }

    return true
  })

  // Listen for Topbar sync button click
  useEffect(() => {
    function handleRequestSync() {
      window.dispatchEvent(new CustomEvent('sync-tab-handled'))
      const targetOrders = !isAdmin
        ? activeDesignerTab === 'todo'
          ? todoOrders
          : activeDesignerTab === 'doing'
          ? doingOrders
          : activeDesignerTab === 'review'
          ? reviewOrders
          : orders
        : filteredOrders
      const targetIds = targetOrders.map((o) => o.id)
      handleSyncPrintervalStatus(targetIds.length > 0 ? targetIds : undefined)
    }
    window.addEventListener('request-sync-current-tab', handleRequestSync)
    return () => window.removeEventListener('request-sync-current-tab', handleRequestSync)
  }, [isAdmin, activeDesignerTab, todoOrders, doingOrders, reviewOrders, orders, filteredOrders])

  // Calculate Metrics
  const totalCount = orders.length
  const openCount = orders.filter(o => o.state === 'OPEN_FOR_ALLOCATION' || o.state === 'DISCOVERED').length
  const inProgressCount = orders.filter(o => o.state === 'IN_PROGRESS' || o.state === 'ASSIGNED').length
  const doneCount = orders.filter(o => o.state === 'DONE' || o.state === 'CLAIMED_IMPORTED').length

  return (
    <DashboardLayout>
      {/* Image Zoom Modal */}
      <ImageModal
        isOpen={!!selectedImage}
        onClose={() => setSelectedImage(null)}
        imageUrl={selectedImage}
      />

      {/* Template Details Modal */}
      <TemplateModal
        isOpen={!!activeTemplateJobs}
        onClose={() => setActiveTemplateJobs(null)}
        templateJobs={activeTemplateJobs?.jobs}
        orderId={activeTemplateJobs?.orderId}
      />

      {/* Flash / Error Banner */}
      {flash && (
        <div className="p-4 rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm font-medium flex items-center justify-between shadow-xs">
          <span>{flash}</span>
          <button onClick={() => setFlash(null)} className="text-emerald-600 hover:text-emerald-900 text-xs font-bold cursor-pointer">X</button>
        </div>
      )}
      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-sm font-medium flex items-center justify-between shadow-xs">
          <span>{error}</span>
          <button onClick={() => setError(null)} className="text-red-600 hover:text-red-900 text-xs font-bold cursor-pointer">X</button>
        </div>
      )}

      {/* Designer Workflow Tabs (Only for Designer) */}
      {!isAdmin && (
        <div className="bg-white p-3 rounded-2xl border border-slate-200 shadow-2xs flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2 overflow-x-auto w-full sm:w-auto pb-1 sm:pb-0">
            <button
              type="button"
              onClick={() => setActiveDesignerTab('todo')}
              className={`px-3.5 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${
                activeDesignerTab === 'todo'
                  ? 'bg-amber-500 text-white border-amber-500 shadow-2xs'
                  : 'bg-amber-50/60 text-amber-900 border-amber-200 hover:bg-amber-100/70'
              }`}
            >
              <span>📌 Việc Cần Làm (Todo)</span>
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${
                  activeDesignerTab === 'todo' ? 'bg-white/20 text-white' : 'bg-amber-200/80 text-amber-900'
                }`}
              >
                {todoOrders.length}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveDesignerTab('doing')}
              className={`px-3.5 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${
                activeDesignerTab === 'doing'
                  ? 'bg-blue-600 text-white border-blue-600 shadow-2xs'
                  : 'bg-blue-50/60 text-blue-900 border-blue-200 hover:bg-blue-100/70'
              }`}
            >
              <span>⚡ Đang Làm (Doing)</span>
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${
                  activeDesignerTab === 'doing' ? 'bg-white/20 text-white' : 'bg-blue-200/80 text-blue-900'
                }`}
              >
                {doingOrders.length}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveDesignerTab('review')}
              className={`px-3.5 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${
                activeDesignerTab === 'review'
                  ? 'bg-purple-600 text-white border-purple-600 shadow-2xs'
                  : 'bg-purple-50/60 text-purple-900 border-purple-200 hover:bg-purple-100/70'
              }`}
            >
              <span>🕒 Chờ Duyệt (Review)</span>
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${
                  activeDesignerTab === 'review' ? 'bg-white/20 text-white' : 'bg-purple-200/80 text-purple-900'
                }`}
              >
                {reviewOrders.length}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveDesignerTab('all')}
              className={`px-3.5 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${
                activeDesignerTab === 'all'
                  ? 'bg-slate-800 text-white border-slate-800 shadow-2xs'
                  : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
              }`}
            >
              <span>Tất Cả Nhiệm Vụ</span>
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${
                  activeDesignerTab === 'all' ? 'bg-white/20 text-white' : 'bg-slate-200 text-slate-700'
                }`}
              >
                {orders.length}
              </span>
            </button>
          </div>

          <button
            type="button"
            onClick={() => handleSyncPrintervalStatus()}
            disabled={syncingPrinterval}
            className="flex items-center gap-2 px-3.5 py-2 text-xs font-semibold bg-purple-50 hover:bg-purple-100 text-purple-700 rounded-xl border border-purple-200 shadow-2xs transition-all cursor-pointer shrink-0 disabled:opacity-50"
            title="Đồng bộ kết quả duyệt/fix từ Printerval"
          >
            <RefreshCw className={`h-3.5 w-3.5 text-purple-600 ${syncingPrinterval ? 'animate-spin' : ''}`} />
            <span>{syncingPrinterval ? 'Đang đồng bộ...' : 'Làm Mới Từ Printerval'}</span>
          </button>
        </div>
      )}

      {/* KPI Summary Cards Grid (For Admin) */}
      {isAdmin && (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Tổng Đơn Hàng</p>
              <h3 className="text-2xl font-bold font-mono text-slate-800 mt-1">{totalCount}</h3>
            </div>
            <div className="p-3 bg-blue-50 text-blue-600 rounded-xl">
              <Package className="h-6 w-6" />
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Mới / Chờ Phân Bổ</p>
              <h3 className="text-2xl font-bold font-mono text-amber-600 mt-1">{openCount}</h3>
            </div>
            <div className="p-3 bg-amber-50 text-amber-600 rounded-xl">
              <Clock className="h-6 w-6" />
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Đang Thực Hiện</p>
              <h3 className="text-2xl font-bold font-mono text-blue-600 mt-1">{inProgressCount}</h3>
            </div>
            <div className="p-3 bg-blue-50 text-blue-600 rounded-xl">
              <Layers className="h-6 w-6" />
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Đã Hoàn Thành / Claim</p>
              <h3 className="text-2xl font-bold font-mono text-emerald-600 mt-1">{doneCount}</h3>
            </div>
            <div className="p-3 bg-emerald-50 text-emerald-600 rounded-xl">
              <CheckCircle2 className="h-6 w-6" />
            </div>
          </div>
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
              placeholder="Tìm theo Mã Đơn, Tên SP, DES..."
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
                {statusOptions.map((s) => (
                  <option key={s} value={s}>
                    {STATE_MAP[s] ? STATE_MAP[s].label : s}
                  </option>
                ))}
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

            {/* Filter by Template */}
            <select
              className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC]"
              value={hasTemplateFilter}
              onChange={(e) => setHasTemplateFilter(e.target.value)}
            >
              <option value="">Tất cả Template</option>
              <option value="yes">Có Template</option>
              <option value="no">Chưa có Template</option>
            </select>

            {user?.role === 'admin' && (
              <input
                className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC] w-28"
                placeholder="Batch ID..."
                value={batchFilter}
                onChange={(e) => setBatchFilter(e.target.value)}
              />
            )}

            {(statusFilter || designerFilter || hasTemplateFilter || batchFilter || searchQuery) && (
              <button
                onClick={() => {
                  setStatusFilter('')
                  setDesignerFilter('')
                  setHasTemplateFilter('')
                  setBatchFilter('')
                  setSearchQuery('')
                }}
                className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800 font-semibold px-2.5 py-1.5 rounded-lg hover:bg-slate-100 cursor-pointer"
              >
                <RotateCcw className="h-3 w-3" />
                <span>Xóa lọc</span>
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Bulk Action Bar (For Admin when orders selected) */}
      {isAdmin && selectedOrderIds.length > 0 && (
        <div className="bg-[#0052CC] text-white px-5 py-3 rounded-xl shadow-lg flex flex-wrap items-center justify-between gap-3 animate-in fade-in slide-in-from-top-2 border border-blue-400/30">
          <div className="flex items-center gap-2">
            <span className="bg-white/20 px-3 py-1 rounded-lg text-xs font-bold font-mono">
              Đã chọn {selectedOrderIds.length} đơn hàng
            </span>
          </div>

          <div className="flex items-center gap-3">
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
              <option value="">-- Chọn Designer phân công --</option>
              {usersList.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name || u.username} ({u.role})
                </option>
              ))}
            </select>

            <select
              value={bulkPrintervalDesigner}
              onChange={(e) => setBulkPrintervalDesigner(e.target.value)}
              disabled={loadingPrintervalOptions}
              className="bg-white text-slate-800 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/30 focus:outline-none shadow-xs disabled:opacity-60"
            >
              <option value="">
                {loadingPrintervalOptions ? 'Đang tải DES Printerval...' : '-- Chọn DES Printerval --'}
              </option>
              {printervalDesigners.map((designer) => (
                <option key={designer} value={designer}>{designer}</option>
              ))}
            </select>

            <select
              value={bulkPrintervalStatus}
              onChange={(e) => setBulkPrintervalStatus(e.target.value)}
              disabled={loadingPrintervalOptions}
              className="bg-white text-slate-800 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/30 focus:outline-none shadow-xs disabled:opacity-60"
            >
              {(printervalStatuses.length ? printervalStatuses : ['Doing']).map((status) => (
                <option key={status} value={status}>{status}</option>
              ))}
            </select>

            <button
              onClick={handleBulkAssign}
              disabled={!bulkDesignerId || !bulkPrintervalDesigner || bulkAssigning || loadingPrintervalOptions}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 text-xs font-bold text-[#0052CC] bg-white hover:bg-slate-100 rounded-lg shadow-sm transition-all disabled:opacity-50 cursor-pointer"
            >
              {bulkAssigning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
              <span>Phân Công {selectedOrderIds.length} Đơn</span>
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

      {/* Dynamic Dense Data Table UI */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-white shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500 tracking-wider">
                {isAdmin && (
                  <th className="py-3 px-3 w-10 text-center">
                    <input
                      type="checkbox"
                      checked={
                        filteredOrders.length > 0 &&
                        filteredOrders.every((o) => selectedOrderIds.includes(o.id))
                      }
                      onChange={(e) => handleSelectAll(e.target.checked)}
                      className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] h-3.5 w-3.5 cursor-pointer"
                    />
                  </th>
                )}
                <th className="py-3 px-4 w-14 text-center">Ảnh</th>
                <th className="py-3 px-4">Mã Đơn Hàng</th>
                <th className="py-3 px-4">Trạng Thái</th>
                <th className="py-3 px-4">DES Đảm Nhận</th>
                <th className="py-3 px-4">Template</th>
                <th className="py-3 px-4">Deadline Printerval</th>
                <th className="py-3 px-4">Ngày Tạo</th>
                <th className="py-3 px-4 text-right">Thao Tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs">
              {filteredOrders.length === 0 ? (
                <tr>
                  <td colSpan={isAdmin ? 9 : 8} className="py-12 text-center text-slate-400">
                    <Package className="h-10 w-10 mx-auto mb-2 opacity-30" />
                    <p className="font-medium text-sm text-slate-500">Không tìm thấy đơn hàng nào</p>
                    <p className="text-xs text-slate-400 mt-1">Thử thay đổi bộ lọc hoặc quét đơn mới từ Printerval</p>
                  </td>
                </tr>
              ) : (
                filteredOrders.map((o) => {
                  const isSelected = selectedOrderIds.includes(o.id)
                  const isNewlyCrawled = newlyCrawledOrderIds.includes(o.id)

                  return (
                    <tr
                      key={o.id}
                      onClick={() => isNewlyCrawled && dismissHighlight(o.id)}
                      className={`transition-all duration-300 ${
                        isNewlyCrawled
                          ? 'bg-emerald-50/80 border-l-4 border-l-emerald-500 shadow-xs'
                          : isSelected
                          ? 'bg-blue-50/80 font-medium'
                          : 'hover:bg-blue-50/40'
                      }`}
                    >
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
                      {/* Image Thumbnail with Click-to-Zoom */}
                      <td className="py-2.5 px-4 text-center">
                        {o.thumbnail_url ? (
                          <img
                            src={resolveAssetUrl(o.thumbnail_url)}
                            alt={o.external_order_id}
                            title="Click để xem ảnh to"
                            onClick={() => setSelectedImage(resolveAssetUrl(o.thumbnail_url) ?? null)}
                            className="h-10 w-10 rounded-lg object-cover border border-slate-200 mx-auto shadow-2xs cursor-pointer hover:scale-105 transition-transform hover:ring-2 hover:ring-[#0052CC]"
                          />
                        ) : (
                          <div className="h-10 w-10 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
                            <Package className="h-5 w-5" />
                          </div>
                        )}
                      </td>

                      {/* Order Code */}
                      <td className="py-2.5 px-4 font-mono font-semibold text-[#0052CC]">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <Link
                            to={`/orders/${o.id}`}
                            onClick={() => isNewlyCrawled && dismissHighlight(o.id)}
                            className="hover:underline flex items-center gap-1"
                          >
                            <span>{o.external_order_id}</span>
                          </Link>
                          {isNewlyCrawled && (
                            <span
                              onClick={(e) => {
                                e.stopPropagation()
                                dismissHighlight(o.id)
                              }}
                              className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 font-black bg-emerald-600 text-white rounded-full animate-pulse shadow-2xs cursor-pointer"
                              title="Đơn mới crawl về! Click để tắt highlight"
                            >
                              ⚡ MỚI CRAWL
                            </span>
                          )}
                        </div>
                        <div className="flex items-center gap-2 mt-1 flex-wrap">
                          {o.sku_image_url && (
                            <a
                              href={o.sku_image_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[10px] font-bold text-[#0052CC] hover:underline inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-blue-50 border border-blue-100"
                              title="Xem ảnh SKU Printerval"
                            >
                              <span>Image</span>
                              <ExternalLink className="h-2.5 w-2.5" />
                            </a>
                          )}
                          {o.external_order_url && (
                            <a
                              href={o.external_order_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[10px] font-bold text-[#0052CC] hover:underline inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-blue-50 border border-blue-100"
                              title="Mở đơn trên Printerval"
                            >
                              <span>Order</span>
                              <ExternalLink className="h-2.5 w-2.5" />
                            </a>
                          )}
                          {o.source_files && o.source_files.length > 0 && (
                            <span className="text-[10px] font-bold text-slate-600 px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200">
                              {o.source_files.length} file source
                            </span>
                          )}
                        </div>

                        {/* Note Outsource Preview for Fix orders */}
                        {o.state === 'REVISION' && o.note_outsource && (
                          <div className="mt-2 p-2.5 rounded-lg bg-orange-50 border border-orange-200 text-[11px] text-orange-950 font-normal">
                            <div className="font-bold flex items-center gap-1 text-orange-900 mb-1">
                              <AlertTriangle className="h-3 w-3 text-orange-600 shrink-0" />
                              <span>QC Printerval yêu cầu sửa:</span>
                            </div>
                            <div className="whitespace-pre-wrap break-all leading-relaxed text-slate-800 max-h-24 overflow-y-auto">
                              {o.note_outsource}
                            </div>
                          </div>
                        )}
                      </td>

                      {/* Interactive Status Dropdown */}
                      <td className="py-2.5 px-4">
                        <StatusDropdown
                          orderId={o.id}
                          externalOrderId={o.external_order_id}
                          currentState={o.state}
                          onStatusChanged={(newState) => {
                            setOrders((prev) =>
                              prev.map((item) => (item.id === o.id ? { ...item, state: newState } : item))
                            )
                          }}
                        />
                      </td>

                      {/* DES Đảm Nhận */}
                      <td className="py-2.5 px-4 font-medium text-slate-700">
                        {o.assigned_designer_name ? (
                          <span
                            onClick={() => isAdmin && setAssigningOrder(o)}
                            className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-blue-50 text-[#0052CC] font-semibold ${
                              isAdmin ? 'cursor-pointer hover:bg-blue-100 hover:scale-105 transition-all' : ''
                            }`}
                            title={isAdmin ? 'Click để đổi Designer đảm nhận' : undefined}
                          >
                            <User className="h-3 w-3" />
                            <span>{o.assigned_designer_name}</span>
                          </span>
                        ) : (
                          <span
                            onClick={() => isAdmin && setAssigningOrder(o)}
                            className={`text-slate-400 font-normal ${
                              isAdmin ? 'cursor-pointer hover:text-[#0052CC] hover:underline font-semibold' : ''
                            }`}
                            title={isAdmin ? 'Click để phân công Designer' : undefined}
                          >
                            {isAdmin ? '+ Phân công DES' : 'Chưa phân bổ'}
                          </span>
                        )}
                        {(o.printerval_designer || o.printerval_status) && (
                          <p className="mt-1 text-[10px] font-medium text-slate-500">
                            Printerval: {o.printerval_designer || '—'}
                            {o.printerval_status ? ` · ${o.printerval_status}` : ''}
                            {o.printerval_assignment_lifecycle === 'pending' && (
                              <span className="inline-flex items-center gap-1">
                                <span> · đang đồng bộ</span>
                                <Loader2 className="h-3 w-3 animate-spin text-[#0052CC]" aria-label="Đang đồng bộ Printerval" />
                              </span>
                            )}
                          </p>
                        )}
                      </td>

                      {/* Template Button */}
                      <td className="py-2.5 px-4">
                        {o.template_jobs && o.template_jobs.length > 0 ? (
                          <button
                            onClick={() => setActiveTemplateJobs({ jobs: o.template_jobs!, orderId: o.external_order_id })}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-lg transition-colors shadow-2xs cursor-pointer"
                          >
                            <FileText className="h-3 w-3" />
                            <span>Xem template của job</span>
                          </button>
                        ) : (
                          <span className="text-slate-300">-</span>
                        )}
                      </td>

                      {/* Deadline */}
                      <td className="py-2.5 px-4 font-mono text-slate-600">
                        {o.deadline_at_ext ? (
                          <span>{new Date(o.deadline_at_ext).toLocaleString('vi-VN')}</span>
                        ) : (
                          <span className="text-slate-300">-</span>
                        )}
                      </td>

                      {/* Created At */}
                      <td className="py-2.5 px-4 font-mono text-slate-500">
                        {new Date(o.created_at).toLocaleDateString('vi-VN')}
                      </td>

                      {/* Actions */}
                      <td className="py-2.5 px-4 text-right">
                        <Link
                          to={`/orders/${o.id}`}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-[#0052CC] hover:text-[#003D99] hover:bg-blue-50 px-2.5 py-1 rounded-md transition-colors"
                        >
                          <span>Chi tiết</span>
                          <ChevronRight className="h-3.5 w-3.5" />
                        </Link>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Assign Order Modal */}
      {assigningOrder && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
          onClick={() => setAssigningOrder(null)}
        >
          <div
            className="relative w-full max-w-sm bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col border border-slate-200"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50">
              <div className="flex items-center gap-2">
                <UserPlus className="h-5 w-5 text-[#0052CC]" />
                <h2 className="text-base font-bold text-slate-800">Phân Công Designer</h2>
              </div>
              <button
                onClick={() => setAssigningOrder(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleAssignOrder} className="p-6 space-y-4">
              <div className="text-xs space-y-1">
                <p className="text-slate-500 font-medium">
                  Đơn hàng: <strong className="text-slate-800 font-mono">{assigningOrder.external_order_id}</strong>
                </p>
                {assigningOrder.product_name && (
                  <p className="text-slate-600 line-clamp-1 font-semibold">{assigningOrder.product_name}</p>
                )}
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Chọn Designer / Người Đảm Nhận <span className="text-red-500">*</span>
                </label>
                <select
                  required
                  value={selectedUserId}
                  onChange={(e) => setSelectedUserId(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
                >
                  <option value="">-- Chọn tài khoản --</option>
                  {usersList.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name || u.username} ({u.role})
                    </option>
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
                  value={selectedPrintervalDesigner}
                  onChange={(e) => setSelectedPrintervalDesigner(e.target.value)}
                  disabled={loadingPrintervalOptions}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] disabled:bg-slate-100"
                >
                  <option value="">
                    {loadingPrintervalOptions ? 'Đang tải danh sách...' : '-- Chọn Designer Printerval --'}
                  </option>
                  {printervalDesigners.map((designer) => (
                    <option key={designer} value={designer}>{designer}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Trạng thái trên Printerval <span className="text-red-500">*</span>
                </label>
                <select
                  required
                  value={selectedPrintervalStatus}
                  onChange={(e) => setSelectedPrintervalStatus(e.target.value)}
                  disabled={loadingPrintervalOptions}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] disabled:bg-slate-100"
                >
                  {(printervalStatuses.length ? printervalStatuses : ['Doing']).map((status) => (
                    <option key={status} value={status}>{status}</option>
                  ))}
                </select>
              </div>

              <div className="pt-3 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setAssigningOrder(null)}
                  className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={assigning || loadingPrintervalOptions || !selectedUserId || !selectedPrintervalDesigner}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl transition-colors shadow-2xs disabled:opacity-50 cursor-pointer"
                >
                  {assigning && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>{assigning ? 'Đang phân công...' : 'Xác Nhận'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </DashboardLayout>
  )
}
