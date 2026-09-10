import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { apiFetch, ApiError, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { usePlatform } from '../auth/PlatformContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { ImageModal } from '../components/ImageModal'
import { StatusDropdown } from '../components/StatusDropdown'
import { Pagination, paginate } from '../components/Pagination'
import { useSyncStatus } from '../hooks/useSyncStatus'
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
  product_skus: { sku?: string | null }[] | null
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
  printerval_designer_option?: string | null
}

type PrintervalStatusTarget = {
  orderIds: string[]
  title: string
  currentStatus?: string | null
}

const PRINTERVAL_STATUS_OPTIONS = ['Waiting', 'Doing', 'Review', 'Fix', 'Confirm', 'Done'] as const

const ORDERS_CACHE_PREFIX = 'tacahu-orders-cache'

function getOrdersCacheKey(platformId: string | undefined, query: string) {
  return `${ORDERS_CACHE_PREFIX}:${platformId || localStorage.getItem('activePlatformId') || 'default'}:${query || 'all'}`
}

function readOrdersCache(key: string): OrderSummary[] | null {
  try {
    const raw = sessionStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { orders?: OrderSummary[]; savedAt?: number }
    if (!Array.isArray(parsed.orders) || !parsed.savedAt || Date.now() - parsed.savedAt > 15 * 60_000) return null
    return parsed.orders
  } catch {
    return null
  }
}

function writeOrdersCache(key: string, orders: OrderSummary[]) {
  try {
    sessionStorage.setItem(key, JSON.stringify({ orders, savedAt: Date.now() }))
  } catch {
    // Private browsing can disable storage; the API remains the source of truth.
  }
}

export function OrdersListPage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user } = useAuth()
  const { activePlatform } = usePlatform()
  const isAdmin = user?.role === 'admin'
  const [orders, setOrders] = useState<OrderSummary[]>(() => readOrdersCache(getOrdersCacheKey(undefined, '')) ?? [])
  const [ordersLoading, setOrdersLoading] = useState(() => readOrdersCache(getOrdersCacheKey(undefined, '')) === null)
  const [statusFilter, setStatusFilter] = useState('')
  const [designerFilter, setDesignerFilter] = useState('')
  const [batchFilter, setBatchFilter] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [flash, setFlash] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeDesignerTab, setActiveDesignerTab] = useState<'todo' | 'doing' | 'review' | 'all'>('todo')
  const [adminTab, setAdminTab] = useState<'unprocessed' | 'processed' | 'all'>('unprocessed')
  const [kpiFilter, setKpiFilter] = useState<'all' | 'open' | 'in_progress' | 'done' | null>(null)
  const { status: syncStatus, triggerRun, isTriggering } = useSyncStatus()
  const [currentPage, setCurrentPage] = useState(() => {
    const parsed = Number(searchParams.get('page') || '1')
    return Number.isInteger(parsed) && parsed > 0 ? parsed : 1
  })
  const activeView = searchParams.get('view') === 'sync' ? 'sync' : 'list'

  // Highlight state for newly crawled jobs
  const [newlyCrawledOrderIds, setNewlyCrawledOrderIds] = useState<string[]>([])

  // Modals state
  const [selectedImage, setSelectedImage] = useState<string | null>(null)

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

  // Status-only Printerval update. This deliberately does not require a Designer.
  const [printervalStatusTarget, setPrintervalStatusTarget] = useState<PrintervalStatusTarget | null>(null)
  const [printervalStatusValue, setPrintervalStatusValue] = useState<string>('Doing')
  const [updatingPrintervalStatus, setUpdatingPrintervalStatus] = useState(false)

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
    const pageOrders = paginate(filteredOrders, currentPage)
    if (checked) {
      setSelectedOrderIds(pageOrders.map((o) => o.id))
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
      const res = await apiFetch<{ queued_count: number }>('/assignments', {
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
      await apiFetch<{ request_ids: string[]; queued_count: number }>(
        '/assignments',
        {
          method: 'POST',
          body: JSON.stringify({
            order_ids: [assigningOrder.id],
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

  function openPrintervalStatusModal(
    orderIds: string[],
    title: string,
    currentStatus?: string | null,
  ) {
    const matchingStatus = PRINTERVAL_STATUS_OPTIONS.find(
      (status) => status.toLowerCase() === currentStatus?.toLowerCase(),
    )
    setPrintervalStatusValue(matchingStatus || 'Doing')
    setPrintervalStatusTarget({ orderIds, title, currentStatus })
  }

  async function handleUpdatePrintervalStatus(e: React.FormEvent) {
    e.preventDefault()
    if (!printervalStatusTarget || printervalStatusTarget.orderIds.length === 0) return
    setUpdatingPrintervalStatus(true)
    try {
      const result = await apiFetch<{ queued_count: number }>('/assignments', {
        method: 'POST',
        body: JSON.stringify({
          order_ids: printervalStatusTarget.orderIds,
          printerval_status: printervalStatusValue,
        }),
      })
      setFlash(
        `Đã xếp cập nhật trạng thái ${printervalStatusValue} trên Printerval cho ${result.queued_count} đơn.`,
      )
      printervalStatusTarget.orderIds.forEach(dismissHighlight)
      setSelectedOrderIds([])
      setPrintervalStatusTarget(null)
      loadOrders()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể xếp cập nhật trạng thái trên Printerval.')
    } finally {
      setUpdatingPrintervalStatus(false)
    }
  }

  async function loadOrders() {
    const params = new URLSearchParams()
    if (statusFilter) params.set('status', statusFilter)
    if (batchFilter) params.set('batch_id', batchFilter)
    if (designerFilter && designerFilter !== 'unassigned') params.set('designer_id', designerFilter)
    if (designerFilter === 'unassigned') params.set('designer_id', 'unassigned')
    const qs = params.toString()
    setOrdersLoading(true)
    try {
      const data = await apiFetch<{ orders: OrderSummary[] }>(`/orders${qs ? `?${qs}` : ''}`)
      // Detect newly arrived orders without blanking the table while revalidating.
      setOrders((prevOrders) => {
        if (prevOrders.length > 0) {
          const existingIds = new Set(prevOrders.map((o) => o.id))
          const newIds = data.orders.filter((o) => !existingIds.has(o.id)).map((o) => o.id)
          if (newIds.length > 0) {
            setNewlyCrawledOrderIds((prev) => Array.from(new Set([...prev, ...newIds])))
            setTimeout(() => {
              setNewlyCrawledOrderIds((prev) => prev.filter((id) => !newIds.includes(id)))
            }, 180000)
          }
        }
        return data.orders
      })
      writeOrdersCache(getOrdersCacheKey(activePlatform?.id, qs), data.orders)
    } finally {
      setOrdersLoading(false)
    }
  }



  useEffect(() => {
    const params = new URLSearchParams()
    if (statusFilter) params.set('status', statusFilter)
    if (batchFilter) params.set('batch_id', batchFilter)
    if (designerFilter) params.set('designer_id', designerFilter)
    const cachedOrders = readOrdersCache(getOrdersCacheKey(activePlatform?.id, params.toString()))
    if (cachedOrders !== null) {
      setOrders(cachedOrders)
      setOrdersLoading(false)
    } else {
      setOrders([])
      setOrdersLoading(true)
    }
    loadOrders().catch((e) => {
      setError(e instanceof ApiError ? e.message : 'Không tải được danh sách đơn.')
    })

    function handleOrdersUpdated() {
      loadOrders().catch(() => {})
    }
    window.addEventListener('orders-updated', handleOrdersUpdated)
    return () => window.removeEventListener('orders-updated', handleOrdersUpdated)
  }, [activePlatform?.id, statusFilter, batchFilter, designerFilter])

  async function handleSyncPrintervalStatus(orderIds?: string[]) {
    if (orderIds && orderIds.length > 500) {
      setError('Tab hiện tại có quá 500 đơn. Hãy thu hẹp bộ lọc trước khi đồng bộ.')
      return
    }
    window.dispatchEvent(new CustomEvent('sync-printerval-start'))
    try {
      await triggerRun(orderIds)
      setFlash('Đã xếp đồng bộ trạng thái Printerval trong nền.')
      window.dispatchEvent(new CustomEvent('sync-printerval-submitted'))
    } catch (err: any) {
      setError(err?.message || 'Lỗi khi đồng bộ từ Printerval.')
    }
  }

  useEffect(() => {
    if (syncStatus && !syncStatus.is_running && syncStatus.last_finished_at) {
      loadOrders().catch(() => {})
    }
  }, [syncStatus?.is_running, syncStatus?.last_finished_at])

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

  // Calculate Admin Workflow groups
  const unprocessedOrders = orders.filter(
    (o) => !['DONE', 'CLAIMED_IMPORTED', 'COMPLETED', 'CANCELLED'].includes(o.state.toUpperCase())
  )
  const processedOrders = orders.filter((o) =>
    ['DONE', 'CLAIMED_IMPORTED', 'COMPLETED'].includes(o.state.toUpperCase())
  )

  // Calculate Metrics
  const totalCount = orders.length
  const openCount = orders.filter(
    (o) => ['OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING', 'WAITING'].includes(o.state.toUpperCase())
  ).length
  const inProgressCount = orders.filter(
    (o) => ['IN_PROGRESS', 'ASSIGNED'].includes(o.state.toUpperCase())
  ).length
  const doneCount = orders.filter(
    (o) => ['DONE', 'CLAIMED_IMPORTED', 'COMPLETED'].includes(o.state.toUpperCase())
  ).length

  // Printerval status breakdown
  const printervalCounts = useMemo(() => {
    const counts = { waiting: 0, doing: 0, review: 0, fix: 0, done: 0 }
    for (const o of orders) {
      const s = (o.printerval_status || '').toLowerCase().trim()
      if (s === 'waiting') counts.waiting++
      else if (s === 'doing') counts.doing++
      else if (s === 'review') counts.review++
      else if (s === 'fix') counts.fix++
      else if (s === 'done') counts.done++
    }
    return counts
  }, [orders])

  let baseOrders = orders
  if (!isAdmin) {
    baseOrders =
      activeDesignerTab === 'todo'
        ? todoOrders
        : activeDesignerTab === 'doing'
        ? doingOrders
        : activeDesignerTab === 'review'
        ? reviewOrders
        : orders
  } else {
    if (kpiFilter === 'open') {
      baseOrders = orders.filter((o) =>
        ['OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING', 'WAITING'].includes(o.state.toUpperCase())
      )
    } else if (kpiFilter === 'in_progress') {
      baseOrders = orders.filter((o) => ['IN_PROGRESS', 'ASSIGNED'].includes(o.state.toUpperCase()))
    } else if (kpiFilter === 'done') {
      baseOrders = orders.filter((o) =>
        ['DONE', 'CLAIMED_IMPORTED', 'COMPLETED'].includes(o.state.toUpperCase())
      )
    } else if (adminTab === 'unprocessed') {
      baseOrders = unprocessedOrders
    } else if (adminTab === 'processed') {
      baseOrders = processedOrders
    } else {
      baseOrders = orders
    }
  }

  // Filter client-side order list & sort newest first
  const filteredOrders = baseOrders
    .filter((o) => {
      if (searchQuery) {
        const q = searchQuery.toLowerCase().trim()
        const matches =
          o.external_order_id.toLowerCase().includes(q) ||
          (o.product_name && o.product_name.toLowerCase().includes(q)) ||
          (o.assigned_designer_name && o.assigned_designer_name.toLowerCase().includes(q)) ||
          (o.printerval_designer && o.printerval_designer.toLowerCase().includes(q))
        if (!matches) return false
      }

      if (statusFilter) {
        const sf = statusFilter.toUpperCase()
        const oState = (o.state || '').toUpperCase()
        const pState = (o.printerval_status || '').toUpperCase()
        if (sf === 'WAITING' || sf === 'OPEN_FOR_ALLOCATION' || sf === 'DISCOVERED' || sf === 'PENDING') {
          if (!['WAITING', 'OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING'].includes(oState) && pState !== 'WAITING') {
            return false
          }
        } else if (sf === 'DOING' || sf === 'IN_PROGRESS' || sf === 'ASSIGNED') {
          if (!['IN_PROGRESS', 'ASSIGNED'].includes(oState) && pState !== 'DOING') {
            return false
          }
        } else if (sf === 'REVIEW' || sf === 'QC_PENDING') {
          if (!['QC_PENDING', 'RESULT_SUBMITTED', 'SUBMITTING_TO_SITE', 'REVIEW'].includes(oState) && pState !== 'REVIEW') {
            return false
          }
        } else if (sf === 'FIX' || sf === 'REVISION') {
          if (!['REVISION', 'REVISION_REQUESTED', 'FIX'].includes(oState) && pState !== 'FIX') {
            return false
          }
        } else if (sf === 'DONE' || sf === 'CLAIMED_IMPORTED' || sf === 'COMPLETED') {
          if (!['DONE', 'CLAIMED_IMPORTED', 'COMPLETED'].includes(oState) && pState !== 'DONE') {
            return false
          }
        } else if (sf === 'CANCELLED') {
          if (oState !== 'CANCELLED' && pState !== 'CANCELLED') {
            return false
          }
        } else {
          if (oState !== sf && pState !== sf) return false
        }
      }

      if (designerFilter) {
        if (designerFilter === 'unassigned') {
          if (o.assigned_designer_name || o.printerval_designer) return false
        } else {
          const desUser = usersList.find((u) => u.id === designerFilter)
          if (desUser) {
            const name = (desUser.full_name || desUser.username || '').toLowerCase().trim()
            const opt = (desUser.printerval_designer_option || '').toLowerCase().trim()
            const assigned = (o.assigned_designer_name || '').toLowerCase().trim()
            const pDes = (o.printerval_designer || '').toLowerCase().trim()
            const matches =
              (name && assigned === name) ||
              (name && pDes === name) ||
              (opt && pDes === opt) ||
              (name && pDes.includes(name))
            if (!matches) return false
          }
        }
      }

      if (batchFilter) {
        const bf = batchFilter.toLowerCase().trim()
        if (bf && o.batch_id !== batchFilter && !o.external_order_id.toLowerCase().includes(bf)) {
          return false
        }
      }

      return true
    })
    .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime())

  // Reset page when filters change
  useEffect(() => {
    setCurrentPage(1)
    const next = new URLSearchParams(searchParams)
    next.delete('page')
    setSearchParams(next, { replace: true })
  }, [statusFilter, designerFilter, batchFilter, searchQuery, activeDesignerTab, adminTab, kpiFilter])

  function setOrdersView(view: 'list' | 'sync') {
    const next = new URLSearchParams(searchParams)
    if (view === 'sync') next.set('view', 'sync')
    else next.delete('view')
    setSearchParams(next)
  }

  function handlePageChange(page: number) {
    setCurrentPage(page)
    const next = new URLSearchParams(searchParams)
    if (page > 1) next.set('page', String(page))
    else next.delete('page')
    setSearchParams(next, { replace: true })
  }

  const paginatedOrders = paginate(filteredOrders, currentPage)

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

  return (
    <DashboardLayout>
      {/* Image Zoom Modal */}
      <ImageModal
        isOpen={!!selectedImage}
        onClose={() => setSelectedImage(null)}
        imageUrl={selectedImage}
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

      {isAdmin && (
        <div className="flex items-center gap-2 border-b border-slate-200">
          <button
            type="button"
            onClick={() => setOrdersView('list')}
            className={`px-3 py-2 text-xs font-bold border-b-2 ${activeView === 'list' ? 'border-[#0052CC] text-[#0052CC]' : 'border-transparent text-slate-500 hover:text-slate-800'}`}
          >
            Danh sách
          </button>
          <button
            type="button"
            onClick={() => setOrdersView('sync')}
            className={`px-3 py-2 text-xs font-bold border-b-2 ${activeView === 'sync' ? 'border-[#0052CC] text-[#0052CC]' : 'border-transparent text-slate-500 hover:text-slate-800'}`}
          >
            Lấy trạng thái từ Printerval
          </button>
        </div>
      )}

      {isAdmin && activeView === 'sync' && (
        <div className="rounded-xl border border-blue-200 bg-blue-50/50 p-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-sm font-bold text-slate-800">Lấy trạng thái từ Printerval</p>
            <p className="mt-1 text-xs text-slate-600">
              {syncStatus?.is_running
                ? `Đang kiểm tra ${syncStatus.last_result?.processed || 0}/${syncStatus.last_result?.total || filteredOrders.length} đơn.`
                : `Sẽ kiểm tra ${filteredOrders.length} đơn đang được lọc. Kết quả được lưu lại nếu mày tải lại trang.`}
            </p>
            {syncStatus?.last_error && <p className="mt-1 text-xs text-red-700">Lỗi gần nhất: {syncStatus.last_error}</p>}
          </div>
          <button
            type="button"
            onClick={() => handleSyncPrintervalStatus(filteredOrders.map((order) => order.id))}
            disabled={isTriggering || !!syncStatus?.is_running || filteredOrders.length === 0 || filteredOrders.length > 500}
            className="inline-flex items-center gap-2 rounded-lg bg-[#0052CC] px-3.5 py-2 text-xs font-bold text-white disabled:opacity-50"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isTriggering || syncStatus?.is_running ? 'animate-spin' : ''}`} />
            {filteredOrders.length > 500 ? 'Thu hẹp bộ lọc (tối đa 500)' : `Lấy trạng thái ${filteredOrders.length} đơn`}
          </button>
        </div>
      )}

      {/* KPI Summary Cards Grid (For Admin) - Interactive Filters */}
      {isAdmin && (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
          <div
            onClick={() => {
              setKpiFilter(kpiFilter === 'all' ? null : 'all')
              setAdminTab('all')
              setStatusFilter('')
            }}
            className={`rounded-xl border bg-white p-4 sm:p-5 shadow-xs flex items-start justify-between cursor-pointer transition-all hover:shadow-md hover:border-blue-300 select-none ${
              adminTab === 'all' && (kpiFilter === 'all' || kpiFilter === null)
                ? 'border-[#0052CC] ring-2 ring-[#0052CC]/20 bg-blue-50/20'
                : 'border-[hsl(var(--border))]'
            }`}
            title="Click để hiển thị tất cả đơn hàng"
          >
            <div className="flex-1 min-w-0 pr-2">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Tổng Đơn Hàng</p>
              <h3 className="text-2xl font-bold font-mono text-slate-800 mt-1">{totalCount}</h3>
              <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[10px]">
                <span className="inline-flex items-center px-1.5 py-0.5 rounded font-mono font-medium bg-amber-50 text-amber-700 border border-amber-200/80" title="Printerval: waiting">
                  waiting: <strong className="ml-1 font-bold">{printervalCounts.waiting}</strong>
                </span>
                <span className="inline-flex items-center px-1.5 py-0.5 rounded font-mono font-medium bg-blue-50 text-blue-700 border border-blue-200/80" title="Printerval: doing">
                  doing: <strong className="ml-1 font-bold">{printervalCounts.doing}</strong>
                </span>
                <span className="inline-flex items-center px-1.5 py-0.5 rounded font-mono font-medium bg-purple-50 text-purple-700 border border-purple-200/80" title="Printerval: review">
                  review: <strong className="ml-1 font-bold">{printervalCounts.review}</strong>
                </span>
                <span className="inline-flex items-center px-1.5 py-0.5 rounded font-mono font-medium bg-rose-50 text-rose-700 border border-rose-200/80" title="Printerval: fix">
                  fix: <strong className="ml-1 font-bold">{printervalCounts.fix}</strong>
                </span>
                <span className="inline-flex items-center px-1.5 py-0.5 rounded font-mono font-medium bg-emerald-50 text-emerald-700 border border-emerald-200/80" title="Printerval: done">
                  done: <strong className="ml-1 font-bold">{printervalCounts.done}</strong>
                </span>
              </div>
            </div>
            <div className="p-3 bg-blue-50 text-[#0052CC] rounded-xl shrink-0">
              <Package className="h-6 w-6" />
            </div>
          </div>

          <div
            onClick={() => {
              setKpiFilter(kpiFilter === 'open' ? null : 'open')
              setAdminTab('unprocessed')
              setStatusFilter('')
            }}
            className={`rounded-xl border bg-white p-4 sm:p-5 shadow-xs flex items-start justify-between cursor-pointer transition-all hover:shadow-md hover:border-amber-300 select-none ${
              kpiFilter === 'open'
                ? 'border-amber-500 ring-2 ring-amber-500/20 bg-amber-50/30'
                : 'border-[hsl(var(--border))]'
            }`}
            title="Click để lọc đơn Mới / Chờ Phân Bổ"
          >
            <div className="flex-1 min-w-0 pr-2">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Mới / Chờ Phân Bổ</p>
              <h3 className="text-2xl font-bold font-mono text-amber-600 mt-1">{openCount}</h3>
            </div>
            <div className="p-3 bg-amber-50 text-amber-600 rounded-xl shrink-0">
              <Clock className="h-6 w-6" />
            </div>
          </div>

          <div
            onClick={() => {
              setKpiFilter(kpiFilter === 'in_progress' ? null : 'in_progress')
              setAdminTab('unprocessed')
              setStatusFilter('')
            }}
            className={`rounded-xl border bg-white p-4 sm:p-5 shadow-xs flex items-start justify-between cursor-pointer transition-all hover:shadow-md hover:border-blue-300 select-none ${
              kpiFilter === 'in_progress'
                ? 'border-blue-600 ring-2 ring-blue-600/20 bg-blue-50/30'
                : 'border-[hsl(var(--border))]'
            }`}
            title="Click để lọc đơn Đang Thực Hiện"
          >
            <div className="flex-1 min-w-0 pr-2">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Đang Thực Hiện</p>
              <h3 className="text-2xl font-bold font-mono text-blue-600 mt-1">{inProgressCount}</h3>
            </div>
            <div className="p-3 bg-blue-50 text-blue-600 rounded-xl shrink-0">
              <Layers className="h-6 w-6" />
            </div>
          </div>

          <div
            onClick={() => {
              setKpiFilter(kpiFilter === 'done' ? null : 'done')
              setAdminTab('processed')
              setStatusFilter('')
            }}
            className={`rounded-xl border bg-white p-4 sm:p-5 shadow-xs flex items-start justify-between cursor-pointer transition-all hover:shadow-md hover:border-emerald-300 select-none ${
              adminTab === 'processed' || kpiFilter === 'done'
                ? 'border-emerald-500 ring-2 ring-emerald-500/20 bg-emerald-50/30'
                : 'border-[hsl(var(--border))]'
            }`}
            title="Click để lọc đơn Đã Hoàn Thành"
          >
            <div className="flex-1 min-w-0 pr-2">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Đã Hoàn Thành / Claim</p>
              <h3 className="text-2xl font-bold font-mono text-emerald-600 mt-1">{doneCount}</h3>
            </div>
            <div className="p-3 bg-emerald-50 text-emerald-600 rounded-xl shrink-0">
              <CheckCircle2 className="h-6 w-6" />
            </div>
          </div>
        </div>
      )}

      {/* Admin Logic Sub-Tabs (Đơn Chưa Xử Lý vs Đơn Đã Xử Lý) */}
      {isAdmin && (
        <div className="bg-white p-2 rounded-2xl border border-slate-200 shadow-2xs flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2 overflow-x-auto w-full sm:w-auto">
            <button
              type="button"
              onClick={() => {
                setAdminTab('unprocessed')
                setKpiFilter(null)
              }}
              className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${
                adminTab === 'unprocessed' && !kpiFilter
                  ? 'bg-[#0052CC] text-white border-[#0052CC] shadow-2xs'
                  : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
              }`}
            >
              <Clock className="h-3.5 w-3.5" />
              <span>Đơn Chưa Xử Lý (Cần Làm / Đang Làm / Chờ Duyệt)</span>
              <span
                className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${
                  adminTab === 'unprocessed' && !kpiFilter ? 'bg-white/20 text-white' : 'bg-amber-100 text-amber-800'
                }`}
              >
                {unprocessedOrders.length}
              </span>
            </button>

            <button
              type="button"
              onClick={() => {
                setAdminTab('processed')
                setKpiFilter(null)
              }}
              className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${
                adminTab === 'processed' && !kpiFilter
                  ? 'bg-emerald-600 text-white border-emerald-600 shadow-2xs'
                  : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
              }`}
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              <span>Đơn Đã Xử Lý (Hoàn Thành / Claimed)</span>
              <span
                className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${
                  adminTab === 'processed' && !kpiFilter ? 'bg-white/20 text-white' : 'bg-emerald-100 text-emerald-800'
                }`}
              >
                {processedOrders.length}
              </span>
            </button>

            <button
              type="button"
              onClick={() => {
                setAdminTab('all')
                setKpiFilter(null)
              }}
              className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${
                adminTab === 'all' && !kpiFilter
                  ? 'bg-slate-800 text-white border-slate-800 shadow-2xs'
                  : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100'
              }`}
            >
              <Package className="h-3.5 w-3.5" />
              <span>Tất Cả Đơn Hàng</span>
              <span
                className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${
                  adminTab === 'all' && !kpiFilter ? 'bg-white/20 text-white' : 'bg-slate-200 text-slate-700'
                }`}
              >
                {orders.length}
              </span>
            </button>
          </div>
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
              <span>Việc Cần Làm (Todo)</span>
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
              <span>Đang Làm (Doing)</span>
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
              <span>Chờ Duyệt (Review)</span>
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
            disabled={isTriggering || !!syncStatus?.is_running}
            className="flex items-center gap-2 px-3.5 py-2 text-xs font-semibold bg-purple-50 hover:bg-purple-100 text-purple-700 rounded-xl border border-purple-200 shadow-2xs transition-all cursor-pointer shrink-0 disabled:opacity-50"
            title="Đồng bộ kết quả duyệt/fix từ Printerval"
          >
            <RefreshCw className={`h-3.5 w-3.5 text-purple-600 ${isTriggering || syncStatus?.is_running ? 'animate-spin' : ''}`} />
            <span>{isTriggering || syncStatus?.is_running ? 'Đang đồng bộ...' : 'Làm Mới Từ Printerval'}</span>
          </button>
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
                <option value="WAITING">Waiting (Chờ nhận / Chưa làm)</option>
                <option value="DOING">Doing (Đang thực hiện)</option>
                <option value="REVIEW">Review (Chờ duyệt / Nộp bài)</option>
                <option value="FIX">Fix (Yêu cầu sửa lại)</option>
                <option value="DONE">Done (Đã hoàn thành / Claim)</option>
                <option value="CANCELLED">Cancelled (Đã hủy)</option>
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

            {user?.role === 'admin' && (
              <input
                className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC] w-28"
                placeholder="Batch ID..."
                value={batchFilter}
                onChange={(e) => setBatchFilter(e.target.value)}
              />
            )}

            {(statusFilter || designerFilter || batchFilter || searchQuery) && (
              <button
                onClick={() => {
                  setStatusFilter('')
                  setDesignerFilter('')
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
              onClick={() => openPrintervalStatusModal(
                selectedOrderIds,
                `Cập nhật ${selectedOrderIds.length} đơn đã chọn`,
              )}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-[#0052CC] bg-white hover:bg-slate-100 rounded-lg shadow-sm transition-all"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Đổi trạng thái Printerval</span>
            </button>
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
                        paginatedOrders.length > 0 &&
                        paginatedOrders.every((o) => selectedOrderIds.includes(o.id))
                      }
                      onChange={(e) => handleSelectAll(e.target.checked)}
                      className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] h-3.5 w-3.5 cursor-pointer"
                    />
                  </th>
                )}
                <th className="py-3 px-4 w-14 text-center">Ảnh</th>
                <th className="py-3 px-4">{isAdmin ? 'Mã Đơn Hàng' : 'Tên Đơn Hàng'}</th>
                <th className="py-3 px-4">Trạng Thái</th>
                <th className="py-3 px-4">DES Đảm Nhận</th>
                <th className="py-3 px-4">Deadline Printerval</th>
                <th className="py-3 px-4">Ngày Tạo</th>
                <th className="py-3 px-4 text-right">Thao Tác</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs">
              {paginatedOrders.length === 0 ? (
                <tr>
                  <td colSpan={isAdmin ? 8 : 7} className="py-12 text-center text-slate-400">
                    {ordersLoading ? (
                      <>
                        <Loader2 className="h-8 w-8 mx-auto mb-2 animate-spin opacity-50" />
                        <p className="font-medium text-sm text-slate-500">Đang cập nhật danh sách đơn…</p>
                      </>
                    ) : (
                      <>
                        <Package className="h-10 w-10 mx-auto mb-2 opacity-30" />
                        <p className="font-medium text-sm text-slate-500">Không tìm thấy đơn hàng nào</p>
                        <p className="text-xs text-slate-400 mt-1">Thử thay đổi bộ lọc hoặc quét đơn mới từ Printerval</p>
                      </>
                    )}
                  </td>
                </tr>
              ) : (
                paginatedOrders.map((o) => {
                  const isSelected = selectedOrderIds.includes(o.id)
                  const isNewlyCrawled = newlyCrawledOrderIds.includes(o.id)

                  return (
                    <tr
                      key={o.id}
                      onClick={() => {
                        if (isNewlyCrawled) dismissHighlight(o.id)
                        navigate(`/orders/${o.id}`)
                      }}
                      className={`transition-all duration-150 cursor-pointer ${
                        isNewlyCrawled
                          ? 'bg-emerald-50/80 border-l-4 border-l-emerald-500 shadow-xs'
                          : isSelected
                          ? 'bg-blue-50/80 font-medium'
                          : 'hover:bg-blue-50/60'
                      }`}
                      title="Click vào dòng để xem chi tiết đơn hàng"
                    >
                      {isAdmin && (
                        <td className="py-2.5 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="checkbox"
                            checked={isSelected}
                            onChange={() => handleToggleSelect(o.id)}
                            className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] h-3.5 w-3.5 cursor-pointer"
                          />
                        </td>
                      )}
                      {/* Image Thumbnail with Click-to-Zoom */}
                      <td className="py-2.5 px-4 text-center" onClick={(e) => e.stopPropagation()}>
                        {o.thumbnail_url ? (
                          <img
                            src={resolveAssetUrl(o.thumbnail_url)}
                            alt={isAdmin ? o.external_order_id : (o.product_name || 'Đơn thiết kế')}
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

                      {/* Order Code / Product Name */}
                      <td className="py-2.5 px-4 font-semibold text-[#0052CC]">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <Link
                            to={`/orders/${o.id}`}
                            onClick={(e) => {
                              e.stopPropagation()
                              if (isNewlyCrawled) dismissHighlight(o.id)
                            }}
                            className="hover:underline flex items-center gap-1"
                            title={o.product_name || o.external_order_id}
                          >
                            {isAdmin ? (
                              <span className="font-mono">{o.external_order_id}</span>
                            ) : (
                              <span className="line-clamp-2 text-xs font-semibold text-slate-800 hover:text-[#0052CC]">
                                {o.product_name || 'Đơn thiết kế'}
                              </span>
                            )}
                          </Link>
                        </div>
                        {isAdmin && o.product_name && (
                          <p className="text-[11px] text-slate-500 font-normal line-clamp-1 mt-0.5" title={o.product_name}>
                            {o.product_name}
                          </p>
                        )}
                        <div className="flex items-center gap-2 mt-1 flex-wrap" onClick={(e) => e.stopPropagation()}>
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
                          {isAdmin && o.external_order_url && (
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
                          {o.product_skus && o.product_skus.length > 1 && (
                            <span className="text-[10px] font-bold text-slate-600 px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200">
                              {o.product_skus.length} mẫu hàng
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
                      <td className="py-2.5 px-4" onClick={(e) => e.stopPropagation()}>
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
                      <td className="py-2.5 px-4 font-medium text-slate-700" onClick={(e) => e.stopPropagation()}>
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
                        {(o.printerval_designer || o.printerval_status || o.printerval_assignment_lifecycle === 'pending') && (
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
                      <td className="py-2.5 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                        {isAdmin && (
                          <button
                            type="button"
                            onClick={() => openPrintervalStatusModal(
                              [o.id],
                              `Đơn ${o.external_order_id}`,
                              o.printerval_status,
                            )}
                            className="mr-1 inline-flex items-center gap-1 text-xs font-semibold text-slate-600 hover:text-[#0052CC] hover:bg-blue-50 px-2.5 py-1 rounded-md transition-colors"
                            title="Đổi trạng thái đơn trên Printerval"
                          >
                            <RefreshCw className="h-3.5 w-3.5" />
                            <span>Printerval</span>
                          </button>
                        )}
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

        {/* Pagination */}
        <Pagination
          totalItems={filteredOrders.length}
          currentPage={currentPage}
          onPageChange={handlePageChange}
        />
      </div>

      {/* Status-only Printerval update modal */}
      {printervalStatusTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
          onClick={() => !updatingPrintervalStatus && setPrintervalStatusTarget(null)}
        >
          <div
            className="relative w-full max-w-sm overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-6 py-4">
              <div className="flex items-center gap-2">
                <RefreshCw className="h-5 w-5 text-[#0052CC]" />
                <h2 className="text-base font-bold text-slate-800">Cập nhật trạng thái Printerval</h2>
              </div>
              <button
                type="button"
                onClick={() => setPrintervalStatusTarget(null)}
                disabled={updatingPrintervalStatus}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700 disabled:opacity-50"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleUpdatePrintervalStatus} className="space-y-4 p-6">
              <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs text-slate-700">
                <p className="font-bold text-slate-800">{printervalStatusTarget.title}</p>
                {printervalStatusTarget.currentStatus && (
                  <p className="mt-1">Trạng thái Printerval đã lưu: <strong>{printervalStatusTarget.currentStatus}</strong></p>
                )}
              </div>
              <div className="space-y-1">
                <label className="block text-xs font-bold text-slate-700">Trạng thái mới trên Printerval</label>
                <select
                  value={printervalStatusValue}
                  onChange={(e) => setPrintervalStatusValue(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs focus:border-[#0052CC] focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20"
                >
                  {PRINTERVAL_STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>{status}</option>
                  ))}
                </select>
              </div>
              <p className="text-[11px] leading-relaxed text-slate-500">
                Thao tác này đẩy trạng thái lên Printerval. Hệ thống xếp việc vào worker nền và chỉ cập nhật kết quả sau khi Printerval xác nhận.
              </p>
              <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
                <button
                  type="button"
                  onClick={() => setPrintervalStatusTarget(null)}
                  disabled={updatingPrintervalStatus}
                  className="rounded-xl bg-slate-100 px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-200 disabled:opacity-50"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={updatingPrintervalStatus}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[#0052CC] px-4 py-2 text-xs font-bold text-white hover:bg-[#0041A3] disabled:opacity-50"
                >
                  {updatingPrintervalStatus && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {updatingPrintervalStatus ? 'Đang xếp hàng…' : `Cập nhật ${printervalStatusTarget.orderIds.length} đơn`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

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
