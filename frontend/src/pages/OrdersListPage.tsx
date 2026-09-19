import { useEffect, useMemo, useState, useCallback } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { apiFetch, ApiError, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { usePlatform } from '../auth/PlatformContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { ImageModal } from '../components/ImageModal'
import { StatusDropdown } from '../components/StatusDropdown'
import { Pagination, paginate } from '../components/Pagination'
import { CopyableOrderCode } from '../components/CopyableOrderCode'
import { CopyableProductName } from '../components/CopyableProductName'
import { ProductQuickViewModal } from '../components/ProductQuickViewModal'
import { LinkifiedText, OpenExternalLinkButton } from '../components/LinkifiedText'
import { useToast } from '../context/ToastContext'
import { useGallerySync } from '../context/GallerySyncContext'
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
  AlertTriangle,
  ArrowDownUp,
  Flag,
  Check,
  Send,
  Calendar,
  Undo2,
  Images,
  Trash2,
  UserX
} from 'lucide-react'

export type OrderSummary = {
  id: string
  external_order_id: string
  state: string
  work_domain: string
  batch_id: string | null
  product_name: string | null
  sku: string | null
  thumbnail_url: string | null
  assigned_designer_name: string | null
  assigned_designer_id?: string | null
  assignment_id: string | null
  product_skus: { sku?: string | null }[] | null
  order_created_at_ext: string | null
  deadline_at_ext: string | null
  sku_image_url: string | null
  external_order_url: string | null
  source_files: { name: string; url: string }[] | null
  source_download_all_url: string | null
  product_image_urls?: string[] | null
  platform_designer?: string | null
  platform_status?: string | null
  platform_assignment_lifecycle?: string | null
  created_at: string
  status_changed_at?: string | null
  note_outsource?: string | null
  previous_note_outsource?: string | null
  fix_approved_by_admin?: boolean
  fix_rejected_by_admin?: boolean
  designer_note?: string
  admin_note?: string | null
  drive_url?: string | null
  template_missing?: boolean
  duplicate_check_status?: string
  is_paid?: boolean
  paid_at?: string | null
  review_submitted_at?: string | null
}

export type UserOption = {
  id: string
  username: string
  full_name: string
  role: string
  platform_designer_option?: string | null
}

export type PlatformStatusTarget = {
  orderIds: string[]
  title: string
  currentStatus?: string | null
}

const PLATFORM_STATUS_OPTIONS = ['Waiting', 'Doing', 'Review', 'Fix', 'Confirm', 'Done'] as const
const DEFAULT_PLATFORM_DES = 'nguyễn thị thúy hường 2d'
const ORDERS_CACHE_PREFIX = 'tacahu-orders-cache'

function getUtc7DateStr(dateInput: string | null | undefined): string | null {
  if (!dateInput) return null
  const d = new Date(dateInput)
  if (isNaN(d.getTime())) return null
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Ho_Chi_Minh',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(d)
}



function formatUtc7Split(dateInput: string | null | undefined): { time: string; date: string } | null {
  if (!dateInput) return null
  const d = new Date(dateInput)
  if (isNaN(d.getTime())) return null
  const timeStr = new Intl.DateTimeFormat('vi-VN', {
    timeZone: 'Asia/Ho_Chi_Minh',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(d)
  const dateStr = new Intl.DateTimeFormat('vi-VN', {
    timeZone: 'Asia/Ho_Chi_Minh',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(d)
  return { time: timeStr, date: dateStr }
}


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
    // Session storage error ignore
  }
}

export function OrdersListPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const { user } = useAuth()
  const { activePlatform } = usePlatform()
  const isAdmin = user?.role === 'admin'
  const isSupport = user?.role === 'support'
  const isManager = isAdmin || isSupport

  const [orders, setOrders] = useState<OrderSummary[]>(() => readOrdersCache(getOrdersCacheKey(undefined, '')) ?? [])
  const [ordersLoading, setOrdersLoading] = useState(() => readOrdersCache(getOrdersCacheKey(undefined, '')) === null)

  // Admin 5 Sub-Tabs State
  const activeTabParam = searchParams.get('tab') as 'waiting' | 'doing' | 'review' | 'fix' | 'done' | null
  const [adminTab, setAdminTab] = useState<'waiting' | 'doing' | 'review' | 'fix' | 'done'>(() => {
    if (activeTabParam && ['waiting', 'doing', 'review', 'fix', 'done'].includes(activeTabParam)) {
      return activeTabParam
    }
    return 'waiting'
  })

  // Support 3 Sub-Tabs State ('all' | 'duplicate' | 'non_duplicate')
  const supportTabParam = searchParams.get('support_tab') as 'all' | 'duplicate' | 'non_duplicate' | null
  const [supportTab, setSupportTab] = useState<'all' | 'duplicate' | 'non_duplicate'>(() => {
    if (supportTabParam && ['all', 'duplicate', 'non_duplicate'].includes(supportTabParam)) {
      return supportTabParam
    }
    return 'all'
  })
  const [updatingDuplicateStatus, setUpdatingDuplicateStatus] = useState(false)

  // Designer Tab State (Doing, Fix, Review, Waiting Update, Paid)
  const [activeDesignerTab, setActiveDesignerTab] = useState<'doing' | 'fix' | 'review' | 'waiting_update' | 'paid'>('doing')
  const [adminDoingSubFilter, setAdminDoingSubFilter] = useState<'all' | 'missing' | 'normal'>('all')
  const [adminFixSubFilter, setAdminFixSubFilter] = useState<'all' | 'pending' | 'approved' | 'rejected'>('all')

  // Search & Filter State
  const { showToast } = useToast()
  const { syncStatusMap } = useGallerySync()
  const [statusFilter, setStatusFilter] = useState('')
  const [platformStatusFilter, setPlatformStatusFilter] = useState('')
  const [designerFilter, setDesignerFilter] = useState('')
  const [batchFilter, setBatchFilter] = useState('')
  const [searchQuery, setSearchQuery] = useState('')
  const [syncedImagesFilter, setSyncedImagesFilter] = useState(false)

  // Date Filter State (3 Modes: status_changed_at, order_created_at_ext, created_at)
  const [dateFilterType, setDateFilterType] = useState<'status_changed_at' | 'order_created_at_ext' | 'created_at'>('status_changed_at')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [datePreset, setDatePreset] = useState<string>('')

  const setFlash = (msg: string | null) => { if (msg) showToast(msg, 'success') }
  const setError = (err: string | null) => { if (err) showToast(err, 'error') }
  const [dateSort, setDateSort] = useState<{ field: 'order_created_at_ext' | 'created_at' | 'status_changed_at'; direction: 'asc' | 'desc' }>({ field: 'status_changed_at', direction: 'desc' })
  const { status: syncStatus, triggerRun, isTriggering } = useSyncStatus()
  const [currentPage, setCurrentPage] = useState(() => {
    const parsed = Number(searchParams.get('page') || '1')
    return Number.isInteger(parsed) && parsed > 0 ? parsed : 1
  })

  // Review 5-Minute Auto-Sync Countdown
  const [reviewAutoSyncCountdown, setReviewAutoSyncCountdown] = useState(300)

  // Highlight state for newly crawled jobs and recently tab-moved jobs
  const [newlyCrawledOrderIds, setNewlyCrawledOrderIds] = useState<string[]>([])
  const [recentTabMovedOrderIds, setRecentTabMovedOrderIds] = useState<string[]>([])
  const [recentPlatformChanges, setRecentPlatformChanges] = useState<
    Record<string, { statusChanged?: boolean; designerChanged?: boolean; timestamp: number }>
  >({})

  // Modals state
  const [selectedImage, setSelectedImage] = useState<string | null>(null)
  const [quickViewOrderId, setQuickViewOrderId] = useState<string | null>(null)

  // Assignment Modal state
  const [assigningOrder, setAssigningOrder] = useState<OrderSummary | null>(null)
  const [usersList, setUsersList] = useState<UserOption[]>([])
  const [selectedUserId, setSelectedUserId] = useState('')
  const [platformDesigners, setPlatformDesigners] = useState<string[]>([])
  const [platformStatuses, setPlatformStatuses] = useState<string[]>([])
  const [selectedPlatformDesigner, setSelectedPlatformDesigner] = useState(DEFAULT_PLATFORM_DES)
  const [selectedPlatformStatus, setSelectedPlatformStatus] = useState('Doing')
  const [loadingPlatformOptions, setLoadingPlatformOptions] = useState(false)
  const [assigning, setAssigning] = useState(false)

  // Accept Fix Modal state
  const [acceptFixOrder, setAcceptFixOrder] = useState<OrderSummary | null>(null)
  const [acceptFixDesignerId, setAcceptFixDesignerId] = useState('')
  const [acceptFixDesignerNote, setAcceptFixDesignerNote] = useState('')
  const [acceptFixOutsourceNote, setAcceptFixOutsourceNote] = useState('')
  const [acceptFixSubmitting, setAcceptFixSubmitting] = useState(false)

  // Reject Fix Modal state
  const [rejectFixOrder, setRejectFixOrder] = useState<OrderSummary | null>(null)
  const [rejectFixOutsourceNote, setRejectFixOutsourceNote] = useState('')
  const [rejectFixSubmitting, setRejectFixSubmitting] = useState(false)

  // Status-only Web mẹ update modal
  const [platformStatusTarget, setPlatformStatusTarget] = useState<PlatformStatusTarget | null>(null)
  const [platformStatusValue, setPlatformStatusValue] = useState<string>('Doing')
  const [updatingPlatformStatus, setUpdatingPlatformStatus] = useState(false)
  const [flaggingMissingOrderId, setFlaggingMissingOrderId] = useState<string | null>(null)

  // Bulk Selection State & Range Selection
  const [selectedOrderIds, setSelectedOrderIds] = useState<string[]>([])
  const [lastSelectedIndex, setLastSelectedIndex] = useState<number | null>(null)
  const [bulkDesignerId, setBulkDesignerId] = useState<string>('')
  const [bulkPlatformDesigner, setBulkPlatformDesigner] = useState(DEFAULT_PLATFORM_DES)
  const [bulkPlatformStatus, setBulkPlatformStatus] = useState('Doing')
  const [bulkAssigning, setBulkAssigning] = useState<boolean>(false)
  const [movingToDuplicateDomain, setMovingToDuplicateDomain] = useState(false)
  const [deleteConfirmModalOpen, setDeleteConfirmModalOpen] = useState(false)
  const [isBulkDeleting, setIsBulkDeleting] = useState(false)

  // Inline submission state for Designer
  const [inlineSubmissionLinks, setInlineSubmissionLinks] = useState<Record<string, string>>({})
  const [isSubmittingInline, setIsSubmittingInline] = useState<Record<string, boolean>>({})

  const regularDesigners = usersList.filter((candidate) => candidate.role === 'designer')

  // Keep adminTab in sync with searchParams
  useEffect(() => {
    if (activeTabParam && ['waiting', 'doing', 'review', 'fix', 'done'].includes(activeTabParam)) {
      setAdminTab(activeTabParam)
    }
  }, [activeTabParam])

  function handleSwitchAdminTab(tab: 'waiting' | 'doing' | 'review' | 'fix' | 'done') {
    setAdminTab(tab)
    setSelectedOrderIds([])
    const next = new URLSearchParams(searchParams)
    next.set('tab', tab)
    next.delete('page')
    setSearchParams(next)
  }

  useEffect(() => {
    if (isAdmin) {
      apiFetch<UserOption[]>('/users').then(setUsersList).catch(() => { })
    }
  }, [isAdmin])

  // Load Web mẹ options when assigning single order
  useEffect(() => {
    if (!assigningOrder) return
    const matchingUser = usersList.find((u) => {
      if (assigningOrder.assigned_designer_id && u.id === assigningOrder.assigned_designer_id) return true
      if (assigningOrder.assigned_designer_name) {
        const name = assigningOrder.assigned_designer_name.trim().toLowerCase()
        return u.username.toLowerCase() === name || (u.full_name && u.full_name.toLowerCase() === name)
      }
      return false
    })
    setSelectedUserId(matchingUser ? matchingUser.id : '')
    setSelectedPlatformDesigner(assigningOrder.platform_designer || DEFAULT_PLATFORM_DES)
    setSelectedPlatformStatus(assigningOrder.platform_status || 'Doing')
    setLoadingPlatformOptions(true)
    apiFetch<{ designers: string[]; statuses: string[] }>(
      `/orders/${assigningOrder.id}/platform-options`
    )
      .then((result) => {
        setPlatformDesigners(result.designers)
        setPlatformStatuses(result.statuses)
        if (assigningOrder.platform_designer && result.designers.includes(assigningOrder.platform_designer)) {
          setSelectedPlatformDesigner(assigningOrder.platform_designer)
        } else if (result.designers.includes(DEFAULT_PLATFORM_DES)) {
          setSelectedPlatformDesigner(DEFAULT_PLATFORM_DES)
        } else if (result.designers.length > 0) {
          setSelectedPlatformDesigner(result.designers[0])
        }
      })
      .catch((err) => {
        setPlatformDesigners([DEFAULT_PLATFORM_DES])
        setPlatformStatuses(['Doing', 'Review', 'Fix', 'Done', 'Waiting'])
        setSelectedPlatformDesigner(assigningOrder.platform_designer || DEFAULT_PLATFORM_DES)
        setError(err instanceof ApiError ? err.message : 'Không tải được danh sách Designer Print.')
      })
      .finally(() => setLoadingPlatformOptions(false))
  }, [assigningOrder, usersList])

  // Load Web mẹ options for bulk assign
  useEffect(() => {
    const firstOrderId = selectedOrderIds[0]
    if (!firstOrderId) {
      setBulkPlatformDesigner(DEFAULT_PLATFORM_DES)
      return
    }
    setLoadingPlatformOptions(true)
    apiFetch<{ designers: string[]; statuses: string[] }>(
      `/orders/${firstOrderId}/platform-options`
    )
      .then((result) => {
        setPlatformDesigners(result.designers)
        setPlatformStatuses(result.statuses)
        if (result.designers.includes(DEFAULT_PLATFORM_DES)) {
          setBulkPlatformDesigner(DEFAULT_PLATFORM_DES)
        } else if (result.designers.length > 0) {
          setBulkPlatformDesigner(result.designers[0])
        }
      })
      .catch(() => {
        setPlatformDesigners([DEFAULT_PLATFORM_DES])
        setPlatformStatuses(['Doing', 'Review', 'Fix', 'Done', 'Waiting'])
        setBulkPlatformDesigner(DEFAULT_PLATFORM_DES)
      })
      .finally(() => setLoadingPlatformOptions(false))
  }, [selectedOrderIds])

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
      setError(err instanceof ApiError ? err.message : 'Không cập nhật được Designer Print.')
    } finally {
      setLoadingPlatformOptions(false)
    }
  }

  function dismissHighlight(orderId: string) {
    setNewlyCrawledOrderIds((prev) => prev.filter((id) => id !== orderId))
    setRecentTabMovedOrderIds((prev) => prev.filter((id) => id !== orderId))
    setRecentPlatformChanges((prev) => {
      if (!prev[orderId]) return prev
      const next = { ...prev }
      delete next[orderId]
      return next
    })
  }

  function markTabMoved(orderIds: string | string[]) {
    const ids = Array.isArray(orderIds) ? orderIds : [orderIds]
    if (ids.length === 0) return
    setRecentTabMovedOrderIds((prev) => Array.from(new Set([...prev, ...ids])))
    setTimeout(() => {
      setRecentTabMovedOrderIds((prev) => prev.filter((id) => !ids.includes(id)))
    }, 300000)
  }


  function handleSelectAll(checked: boolean) {
    const pageOrders = paginate(filteredOrders, currentPage)
    if (checked) {
      setSelectedOrderIds(pageOrders.map((o) => o.id))
    } else {
      setSelectedOrderIds([])
    }
  }


  async function handleBulkAssign() {
    if (!bulkDesignerId || selectedOrderIds.length === 0) return
    setBulkAssigning(true)
    try {
      const desUser = usersList.find((u) => u.id === bulkDesignerId)
      const platformDes = bulkPlatformDesigner || desUser?.platform_designer_option || DEFAULT_PLATFORM_DES
      const res = await apiFetch<{ queued_count: number }>('/assignments', {
        method: 'POST',
        body: JSON.stringify({
          order_ids: selectedOrderIds,
          designer_id: bulkDesignerId,
          printerval_designer: platformDes,
          printerval_status: bulkPlatformStatus || 'Doing',
        }),
      })
      setFlash(`Đã phân công ${res.queued_count} đơn sang Doing và xếp đồng bộ Print.`)
      markTabMoved(selectedOrderIds)
      setSelectedOrderIds([])
      setBulkDesignerId('')
      setBulkPlatformDesigner(DEFAULT_PLATFORM_DES)
      await loadOrders()
    } catch (err) {
      if (err instanceof ApiError) {
        alert(`Lỗi phân công hàng loạt: ${err.message}`)
      }
    } finally {
      setBulkAssigning(false)
    }
  }

  function handleSwitchSupportTab(tab: 'all' | 'duplicate' | 'non_duplicate') {
    setSupportTab(tab)
    setCurrentPage(1)
    setSelectedOrderIds([])
    const next = new URLSearchParams(searchParams)
    next.set('support_tab', tab)
    next.delete('page')
    setSearchParams(next, { replace: true })
  }

  async function handleSetDuplicateStatus(orderIds: string[], targetStatus: 'duplicate' | 'non_duplicate' | 'uncheck') {
    if (orderIds.length === 0) return
    setUpdatingDuplicateStatus(true)
    try {
      const res = await apiFetch<{ changed_count: number; status: string }>('/orders/duplicate-check-status', {
        method: 'POST',
        body: JSON.stringify({ order_ids: orderIds, status: targetStatus }),
      })
      const statusLabel =
        targetStatus === 'duplicate'
          ? 'Trùng lặp'
          : targetStatus === 'non_duplicate'
            ? 'Không trùng lặp'
            : 'Chưa kiểm tra'
      showToast(`Đã chuyển ${res.changed_count} đơn sang trạng thái "${statusLabel}".`, 'success')
      markTabMoved(orderIds)
      setSelectedOrderIds((prev) => prev.filter((id) => !orderIds.includes(id)))
      await loadOrders()
    } catch (err: any) {
      showToast(err?.message || 'Không thể cập nhật trạng thái trùng lặp.', 'error')
    } finally {
      setUpdatingDuplicateStatus(false)
    }
  }

  async function moveSelectedToDuplicateDomain() {
    if (selectedOrderIds.length === 0) return
    setMovingToDuplicateDomain(true)
    try {
      const result = await apiFetch<{ changed_count: number }>('/orders/duplicate-domain', {
        method: 'POST',
        body: JSON.stringify({ order_ids: selectedOrderIds, work_domain: 'duplicate' }),
      })
      setFlash(`Đã đưa ${result.changed_count} đơn vào domain Đơn trùng lặp.`)
      markTabMoved(selectedOrderIds)
      setSelectedOrderIds([])
      await loadOrders()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể chuyển đơn vào domain Đơn trùng lặp.')
    } finally {
      setMovingToDuplicateDomain(false)
    }
  }

  async function handleBulkDelete() {
    if (!selectedOrderIds.length) return
    setIsBulkDeleting(true)
    try {
      const res = await apiFetch<{ ok: boolean; deleted_count: number }>('/orders/bulk-delete', {
        method: 'POST',
        body: JSON.stringify({ order_ids: selectedOrderIds }),
      })
      setFlash(`Đã xóa vĩnh viễn ${res.deleted_count} đơn hàng khỏi hệ thống.`)
      setSelectedOrderIds([])
      setLastSelectedIndex(null)
      setDeleteConfirmModalOpen(false)
      await loadOrders()
    } catch (err: any) {
      alert(`Lỗi khi xóa đơn hàng: ${err.message || err}`)
    } finally {
      setIsBulkDeleting(false)
    }
  }

  function openAssignModal(order: OrderSummary) {
    setAssigningOrder(order)
  }

  async function handleUnassignCurrentOrder() {
    if (!assigningOrder) return
    const orderId = assigningOrder.id
    const orderCode = assigningOrder.external_order_id
    setAssigning(true)
    try {
      const res = await apiFetch<{ message: string; revoked_count: number }>('/assignments/revoke', {
        method: 'POST',
        body: JSON.stringify({ order_ids: [orderId] }),
      })
      showToast(res.message || `Đã hủy phân công cho đơn ${orderCode}.`, 'success')
      setAssigningOrder(null)
      await loadOrders()
    } catch (err: any) {
      showToast(err?.message || 'Không thể hủy phân công đơn hàng.', 'error')
    } finally {
      setAssigning(false)
    }
  }

  async function handleAssignOrder(e: React.FormEvent) {
    e.preventDefault()
    if (!assigningOrder || !selectedUserId || !selectedPlatformDesigner) return
    setAssigning(true)
    try {
      await apiFetch<{ request_ids: string[]; queued_count: number }>(
        '/assignments',
        {
          method: 'POST',
          body: JSON.stringify({
            order_ids: [assigningOrder.id],
            designer_id: selectedUserId,
            printerval_designer: selectedPlatformDesigner || DEFAULT_PLATFORM_DES,
            printerval_status: selectedPlatformStatus || 'Doing',
          }),
        }
      )
      setFlash(`Đã phân công đơn ${assigningOrder.external_order_id} sang Doing và cập nhật Print.`)
      markTabMoved(assigningOrder.id)
      setAssigningOrder(null)
      await loadOrders()
    } catch (err) {
      if (err instanceof ApiError) {
        alert(`Lỗi phân công: ${err.message}`)
      }
    } finally {
      setAssigning(false)
    }
  }

  function openPlatformStatusModal(
    orderIds: string[],
    title: string,
    currentStatus?: string | null,
  ) {
    const matchingStatus = PLATFORM_STATUS_OPTIONS.find(
      (status) => status.toLowerCase() === currentStatus?.toLowerCase(),
    )
    setPlatformStatusValue(matchingStatus || 'Doing')
    setPlatformStatusTarget({ orderIds, title, currentStatus })
  }

  async function handleUpdatePlatformStatus(e: React.FormEvent) {
    e.preventDefault()
    if (!platformStatusTarget || platformStatusTarget.orderIds.length === 0) return
    setUpdatingPlatformStatus(true)
    try {
      const result = await apiFetch<{ queued_count: number }>('/assignments', {
        method: 'POST',
        body: JSON.stringify({
          order_ids: platformStatusTarget.orderIds,
          platform_status: platformStatusValue,
        }),
      })
      setFlash(
        `Đã xếp cập nhật trạng thái ${platformStatusValue} trên Web mẹ cho ${result.queued_count} đơn.`,
      )
      markTabMoved(platformStatusTarget.orderIds)
      setSelectedOrderIds([])
      setPlatformStatusTarget(null)
      await loadOrders()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không thể xếp cập nhật trạng thái trên Web mẹ.')
    } finally {
      setUpdatingPlatformStatus(false)
    }
  }

  async function handleRevokeAssignment(orderIds: string[]) {
    if (orderIds.length === 0) return
    setError(null)
    try {
      const res = await apiFetch<{ message: string; revoked_count: number }>('/assignments/revoke', {
        method: 'POST',
        body: JSON.stringify({ order_ids: orderIds }),
      })
      showToast(res.message || `Đã hủy chia đơn cho ${orderIds.length} đơn hàng.`, 'success')
      setSelectedOrderIds([])
      await loadOrders()
    } catch (err: any) {
      setError(err?.message || 'Không thể hủy chia đơn.')
      showToast(err?.message || 'Không thể hủy chia đơn.', 'error')
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
      setOrders((prevOrders) => {
        if (prevOrders.length > 0) {
          const prevMap = new Map(prevOrders.map((o) => [o.id, o]))
          const existingIds = new Set(prevOrders.map((o) => o.id))
          const newIds = data.orders.filter((o) => !existingIds.has(o.id)).map((o) => o.id)
          if (newIds.length > 0) {
            setNewlyCrawledOrderIds((prev) => Array.from(new Set([...prev, ...newIds])))
            setTimeout(() => {
              setNewlyCrawledOrderIds((prev) => prev.filter((id) => !newIds.includes(id)))
            }, 300000)
          }

          // Check tab state changes & Web mẹ status/designer changes
          const movedIds: string[] = []
          const nowTs = Date.now()
          const newPrinChanges: Record<string, { statusChanged?: boolean; designerChanged?: boolean; timestamp: number }> = {}

          data.orders.forEach((newOrd) => {
            const oldOrd = prevMap.get(newOrd.id)
            if (oldOrd) {
              if (oldOrd.state !== newOrd.state) {
                movedIds.push(newOrd.id)
              }
              const stChanged = Boolean(oldOrd.platform_status && newOrd.platform_status && oldOrd.platform_status !== newOrd.platform_status)
              const desChanged = Boolean(oldOrd.platform_designer && newOrd.platform_designer && oldOrd.platform_designer !== newOrd.platform_designer)
              if (stChanged || desChanged) {
                newPrinChanges[newOrd.id] = {
                  statusChanged: stChanged,
                  designerChanged: desChanged,
                  timestamp: nowTs,
                }
              }
            }
          })

          if (movedIds.length > 0) {
            setRecentTabMovedOrderIds((prev) => Array.from(new Set([...prev, ...movedIds])))
            setTimeout(() => {
              setRecentTabMovedOrderIds((prev) => prev.filter((id) => !movedIds.includes(id)))
            }, 300000)
          }

          if (Object.keys(newPrinChanges).length > 0) {
            setRecentPlatformChanges((prev) => ({ ...prev, ...newPrinChanges }))
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
      setOrdersLoading(true)
    }
    loadOrders().catch((e) => {
      setError(e instanceof ApiError ? e.message : 'Không tải được danh sách đơn.')
    })

    function handleOrdersUpdated() {
      loadOrders().catch(() => { })
    }
    window.addEventListener('orders-updated', handleOrdersUpdated)
    return () => window.removeEventListener('orders-updated', handleOrdersUpdated)
  }, [activePlatform?.id, statusFilter, batchFilter, designerFilter])

  async function flagMissingTemplate(order: OrderSummary) {
    if (!order.assignment_id) {
      setError('Đơn này chưa có assignment đang hoạt động nên chưa thể báo thiếu temp.')
      return
    }
    setFlaggingMissingOrderId(order.id)
    setError(null)
    try {
      await apiFetch(`/assignments/${order.assignment_id}/flag-missing-template`, {
        method: 'POST',
        body: JSON.stringify({ request_id: crypto.randomUUID() }),
      })
      setFlash(`Đã báo thiếu temp cho đơn ${order.external_order_id}. Đơn đã chuyển sang Chờ cập nhật.`)
      await loadOrders()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể báo thiếu temp.')
    } finally {
      setFlaggingMissingOrderId(null)
    }
  }

  async function handleSyncPlatformStatus(orderIds?: string[]) {
    window.dispatchEvent(new CustomEvent('sync-platform-start'))
    try {
      await triggerRun(orderIds)
      showToast('Đã xếp đồng bộ trạng thái Web mẹ trong nền.', 'info')
      window.dispatchEvent(new CustomEvent('sync-platform-submitted'))
    } catch (err: any) {
      showToast(err?.message || 'Lỗi khi đồng bộ từ Web mẹ.', 'error')
    }
  }


  // Inline submit result link for Designer from outer list
  async function handleInlineSubmit(order: OrderSummary, linkValue: string) {
    const trimmed = (linkValue || '').trim()
    if (!trimmed) {
      showToast('Vui lòng dán link kết quả thiết kế (Drive, Canva, DropBox...) trước khi nộp bài!', 'error')
      return
    }

    setIsSubmittingInline((prev) => ({ ...prev, [order.id]: true }))
    try {
      if (order.assignment_id) {
        try {
          await apiFetch(`/assignments/${order.assignment_id}/results`, {
            method: 'POST',
            body: JSON.stringify({
              drive_url: trimmed,
              request_id: crypto.randomUUID(),
            }),
          })
        } catch (assignErr) {
          console.warn('Ghi nhận assignment result:', assignErr)
        }
      }

      await apiFetch(`/orders/${order.id}/state`, {
        method: 'PATCH',
        body: JSON.stringify({
          state: 'QC_PENDING',
          drive_url: trimmed,
          note_outsource: trimmed,
        }),
      })

      showToast(`Đã nộp bài thiết kế thành công cho đơn: ${order.product_name || order.external_order_id}`, 'success')
      markTabMoved(order.id)
      window.dispatchEvent(new CustomEvent('orders-updated'))
      await loadOrders()
    } catch (err: any) {
      showToast(err?.message || 'Không thể nộp kết quả.', 'error')
    } finally {
      setIsSubmittingInline((prev) => ({ ...prev, [order.id]: false }))
    }
  }

  useEffect(() => {
    if (syncStatus && !syncStatus.is_running && syncStatus.last_finished_at) {
      loadOrders().catch(() => { })
    }
  }, [syncStatus?.is_running, syncStatus?.last_finished_at])

  // Support 3 Sub-Tabs Groups
  // 1. Chưa kiểm tra (chứa toàn bộ đơn waiting và doing chưa kiểm tra của admin)
  const supportUncheckedOrders = useMemo(() => {
    return orders.filter((o) => {
      if (o.work_domain === 'duplicate') return false
      const isUncheck = !o.duplicate_check_status || o.duplicate_check_status === 'uncheck'
      const st = (o.state || '').toUpperCase()
      const isWaitingOrDoing = ['WAITING', 'OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING', 'OPEN', 'IN_PROGRESS', 'DOING', 'ASSIGNED'].includes(st)
      return isUncheck && isWaitingOrDoing
    })
  }, [orders])

  // 2. Trùng lặp (thuộc duplicate domain / trello hoặc đã gắn tag duplicate)
  const supportDuplicateOrders = useMemo(() => {
    return orders.filter((o) => o.work_domain === 'duplicate' || o.duplicate_check_status === 'duplicate')
  }, [orders])

  // 3. Không trùng lặp (đã kiểm tra và đánh dấu không trùng)
  const supportNonDuplicateOrders = useMemo(() => {
    return orders.filter((o) => o.work_domain !== 'duplicate' && o.duplicate_check_status === 'non_duplicate')
  }, [orders])

  // Admin 5 Sub-Tabs Groups (excludes duplicate domain orders from standard tabs)
  const waitingOrders = useMemo(() => {
    return orders.filter((o) => {
      if (o.work_domain === 'duplicate') return false
      const st = (o.state || '').toUpperCase()
      return ['WAITING', 'OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING', 'OPEN'].includes(st)
    })
  }, [orders])

  const doingOrders = useMemo(() => {
    return orders.filter((o) => {
      if (o.work_domain === 'duplicate') return false
      const st = (o.state || '').toUpperCase()
      return ['IN_PROGRESS', 'DOING', 'ASSIGNED'].includes(st)
    })
  }, [orders])

  const missingTemplateDoingOrders = useMemo(() => {
    return doingOrders.filter((o) => !!o.template_missing)
  }, [doingOrders])

  const normalDoingOrders = useMemo(() => {
    return doingOrders.filter((o) => !o.template_missing)
  }, [doingOrders])

  const filteredDoingOrders = useMemo(() => {
    if (adminDoingSubFilter === 'missing') return missingTemplateDoingOrders
    if (adminDoingSubFilter === 'normal') return normalDoingOrders
    return doingOrders
  }, [adminDoingSubFilter, doingOrders, missingTemplateDoingOrders, normalDoingOrders])

  const reviewOrders = useMemo(() => {
    return orders.filter((o) => {
      if (o.work_domain === 'duplicate') return false
      const st = (o.state || '').toUpperCase()
      return ['QC_PENDING', 'RESULT_SUBMITTED', 'SUBMITTING_TO_SITE', 'REVIEW'].includes(st)
    })
  }, [orders])

  const fixOrders = useMemo(() => {
    return orders.filter((o) => {
      if (o.work_domain === 'duplicate') return false
      const st = (o.state || '').toUpperCase()
      return ['REVISION', 'REVISION_REQUESTED', 'FIX'].includes(st)
    })
  }, [orders])

  const pendingFixOrders = useMemo(() => {
    return fixOrders.filter((o) => !o.fix_approved_by_admin && !o.fix_rejected_by_admin)
  }, [fixOrders])

  const approvedFixOrders = useMemo(() => {
    return fixOrders.filter((o) => !!o.fix_approved_by_admin)
  }, [fixOrders])

  const rejectedFixOrders = useMemo(() => {
    return fixOrders.filter((o) => !!o.fix_rejected_by_admin)
  }, [fixOrders])

  const filteredFixOrders = useMemo(() => {
    if (adminFixSubFilter === 'pending') return pendingFixOrders
    if (adminFixSubFilter === 'approved') return approvedFixOrders
    if (adminFixSubFilter === 'rejected') return rejectedFixOrders
    return fixOrders
  }, [adminFixSubFilter, fixOrders, pendingFixOrders, approvedFixOrders, rejectedFixOrders])

  const doneOrders = useMemo(() => {
    return orders.filter((o) => {
      if (o.work_domain === 'duplicate') return false
      const st = (o.state || '').toUpperCase()
      return ['DONE', 'CLAIMED_IMPORTED', 'COMPLETED'].includes(st)
    })
  }, [orders])

  // Review Tab 5-Minute Auto-Sync Interval Timer
  useEffect(() => {
    if (!isAdmin || adminTab !== 'review') return

    const timer = setInterval(() => {
      setReviewAutoSyncCountdown((prev) => {
        if (prev <= 1) {
          const targetIds = reviewOrders.map((o) => o.id)
          if (targetIds.length > 0) {
            handleSyncPlatformStatus(targetIds)
          }
          return 300
        }
        return prev - 1
      })
    }, 1000)

    return () => clearInterval(timer)
  }, [isAdmin, adminTab, reviewOrders])

  // Designer Workflow groups
  const designerDoingOrders = orders.filter(
    (o) =>
      !o.template_missing &&
      !o.is_paid &&
      ['IN_PROGRESS', 'ASSIGNED', 'DOING'].includes(o.state.toUpperCase())
  )
  const designerFixOrders = orders.filter(
    (o) =>
      !o.template_missing &&
      !o.is_paid &&
      ['REVISION', 'REVISION_REQUESTED', 'FIX'].includes(o.state.toUpperCase())
  )
  const designerReviewOrders = orders.filter(
    (o) =>
      !o.template_missing &&
      !o.is_paid &&
      ['QC_PENDING', 'RESULT_SUBMITTED', 'SUBMITTING_TO_SITE', 'REVIEW'].includes(o.state.toUpperCase())
  )
  const waitingUpdateOrders = orders.filter(
    (o) => (o.template_missing || o.state.toUpperCase() === 'WAITING_UPDATE') && !o.is_paid
  )
  const designerPaidOrders = orders.filter((o) => o.is_paid)
  const designerDoneOrders = orders.filter((o) =>
    !o.is_paid && ['DONE', 'CLAIMED_IMPORTED', 'COMPLETED', 'SKIPPED'].includes(o.state.toUpperCase())
  )

  // Base list of orders depending on role and active tab
  let baseOrders: OrderSummary[] = orders
  if (isSupport) {
    baseOrders =
      supportTab === 'all'
        ? supportUncheckedOrders
        : supportTab === 'duplicate'
          ? supportDuplicateOrders
          : supportNonDuplicateOrders
  } else if (isAdmin) {
    baseOrders =
      adminTab === 'waiting'
        ? waitingOrders
        : adminTab === 'doing'
          ? filteredDoingOrders
          : adminTab === 'review'
            ? reviewOrders
            : adminTab === 'fix'
              ? filteredFixOrders
              : doneOrders
  } else {
    baseOrders =
      activeDesignerTab === 'doing'
        ? designerDoingOrders
        : activeDesignerTab === 'fix'
          ? designerFixOrders
          : activeDesignerTab === 'review'
            ? designerReviewOrders
            : activeDesignerTab === 'waiting_update'
              ? waitingUpdateOrders
              : activeDesignerTab === 'paid'
                ? designerPaidOrders
                : designerDoneOrders
  }

  const isOrderGallerySynced = useCallback(
    (o: OrderSummary) => {
      const dbCount =
        o.product_image_urls && o.product_image_urls.length > 0
          ? o.product_image_urls.length
          : o.thumbnail_url
            ? 1
            : 0
      const liveStatus = syncStatusMap[o.id]
      const imgCount =
        liveStatus?.status === 'success' && typeof liveStatus?.count === 'number'
          ? Math.max(liveStatus.count, dbCount)
          : dbCount
      return imgCount > 1
    },
    [syncStatusMap]
  )

  const syncedOrdersCount = useMemo(() => {
    return baseOrders.filter(isOrderGallerySynced).length
  }, [baseOrders, isOrderGallerySynced])

  // Filter client-side order list & sort newest first
  const filteredOrders = baseOrders
    .filter((o) => {
      if (syncedImagesFilter && !isOrderGallerySynced(o)) {
        return false
      }
      if (searchQuery) {
        const q = searchQuery.toLowerCase().trim()
        const matches = isAdmin
          ? o.external_order_id.toLowerCase().includes(q) ||
          (o.product_name && o.product_name.toLowerCase().includes(q)) ||
          (o.assigned_designer_name && o.assigned_designer_name.toLowerCase().includes(q)) ||
          (o.platform_designer && o.platform_designer.toLowerCase().includes(q))
          : (o.product_name && o.product_name.toLowerCase().includes(q))
        if (!matches) return false
      }

      if (statusFilter) {
        const sf = statusFilter.toUpperCase()
        const oState = (o.state || '').toUpperCase()
        const pState = (o.platform_status || '').toUpperCase()
        if (sf === 'WAITING' || sf === 'OPEN_FOR_ALLOCATION' || sf === 'DISCOVERED' || sf === 'PENDING' || sf === 'OPEN') {
          if (!['WAITING', 'OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING', 'OPEN'].includes(oState) && pState !== 'WAITING') {
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
          if (o.assigned_designer_name || o.platform_designer) return false
        } else {
          const desUser = usersList.find((u) => u.id === designerFilter)
          if (desUser) {
            const name = (desUser.full_name || desUser.username || '').toLowerCase().trim()
            const opt = (desUser.platform_designer_option || '').toLowerCase().trim()
            const assigned = (o.assigned_designer_name || '').toLowerCase().trim()
            const pDes = (o.platform_designer || '').toLowerCase().trim()
            const matches =
              (name && assigned === name) ||
              (name && pDes === name) ||
              (opt && pDes === opt) ||
              (name && pDes.includes(name))
            if (!matches) return false
          }
        }
      }

      if (platformStatusFilter) {
        const psf = platformStatusFilter.toLowerCase().trim()
        const orderPStatus = (o.platform_status || '').toLowerCase().trim()
        if (psf === 'unspecified') {
          if (orderPStatus) return false
        } else {
          if (orderPStatus !== psf) return false
        }
      }

      if (batchFilter) {
        const bf = batchFilter.toLowerCase().trim()
        if (bf && o.batch_id !== batchFilter && !o.external_order_id.toLowerCase().includes(bf)) {
          return false
        }
      }

      // Date Range Filter (By dateFilterType in UTC+7)
      if (dateFrom || dateTo) {
        const rawVal = o[dateFilterType] || (dateFilterType === 'status_changed_at' ? o.created_at : null)
        if (!rawVal) return false
        const itemDate = getUtc7DateStr(rawVal)
        if (!itemDate) return false
        if (dateFrom && itemDate < dateFrom) return false
        if (dateTo && itemDate > dateTo) return false
      }

      return true
    })
    .sort((a, b) => {
      const aValue = a[dateSort.field] || (dateSort.field === 'status_changed_at' ? a.created_at : null)
      const bValue = b[dateSort.field] || (dateSort.field === 'status_changed_at' ? b.created_at : null)
      if (!aValue) return bValue ? 1 : 0
      if (!bValue) return -1
      const aTime = new Date(aValue).getTime()
      const bTime = new Date(bValue).getTime()
      return dateSort.direction === 'desc' ? bTime - aTime : aTime - bTime
    })

  // Reset page when filters change
  useEffect(() => {
    setCurrentPage(1)
    const next = new URLSearchParams(searchParams)
    next.delete('page')
    setSearchParams(next, { replace: true })
  }, [statusFilter, platformStatusFilter, designerFilter, batchFilter, searchQuery, dateFilterType, dateFrom, dateTo, activeDesignerTab, adminTab, dateSort, syncedImagesFilter])

  function toggleDateSort(field: 'order_created_at_ext' | 'created_at' | 'status_changed_at') {
    setDateSort((current) => ({
      field,
      direction: current.field === field && current.direction === 'desc' ? 'asc' : 'desc',
    }))
  }

  function applyDatePreset(preset: 'today' | 'yesterday' | '7days' | 'this_month' | 'all') {
    if (preset === 'all') {
      setDatePreset('')
      setDateFrom('')
      setDateTo('')
      return
    }
    setDatePreset(preset)
    const now = new Date()
    const getTodayUtc7 = (dateObj: Date) => {
      return new Intl.DateTimeFormat('en-CA', {
        timeZone: 'Asia/Ho_Chi_Minh',
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      }).format(dateObj)
    }
    const todayStr = getTodayUtc7(now)
    if (preset === 'today') {
      setDateFrom(todayStr)
      setDateTo(todayStr)
    } else if (preset === 'yesterday') {
      const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000)
      const yStr = getTodayUtc7(yesterday)
      setDateFrom(yStr)
      setDateTo(yStr)
    } else if (preset === '7days') {
      const sevenDaysAgo = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000)
      setDateFrom(getTodayUtc7(sevenDaysAgo))
      setDateTo(todayStr)
    } else if (preset === 'this_month') {
      const firstDay = new Date(now.getFullYear(), now.getMonth(), 1)
      setDateFrom(getTodayUtc7(firstDay))
      setDateTo(todayStr)
    }
  }

  function handleResetFilters() {
    setStatusFilter('')
    setPlatformStatusFilter('')
    setDesignerFilter('')
    setBatchFilter('')
    setSearchQuery('')
    setDateFrom('')
    setDateTo('')
    setDatePreset('')
    setSyncedImagesFilter(false)
  }

  function openAcceptFixModal(order: OrderSummary) {
    setAcceptFixOrder(order)
    const currentDes = usersList.find((u) => (u.full_name || u.username) === order.assigned_designer_name)
    setAcceptFixDesignerId(currentDes ? currentDes.id : '')
    setAcceptFixDesignerNote(order.designer_note || '')
    setAcceptFixOutsourceNote(order.note_outsource || '')
  }

  async function handleAcceptFix(e: React.FormEvent) {
    e.preventDefault()
    if (!acceptFixOrder) return
    setAcceptFixSubmitting(true)
    try {
      await apiFetch(`/orders/${acceptFixOrder.id}/approve-fix`, {
        method: 'POST',
        body: JSON.stringify({
          designer_id: acceptFixDesignerId || undefined,
          designer_note: acceptFixDesignerNote,
          note_outsource: acceptFixOutsourceNote,
        }),
      })
      showToast(`Đã chấp nhận Fix và giao bài cho Designer đơn ${acceptFixOrder.external_order_id}.`, 'success')
      markTabMoved(acceptFixOrder.id)
      setAcceptFixOrder(null)
      await loadOrders()
    } catch (err: any) {
      showToast(err?.message || 'Không thể chấp nhận Fix.', 'error')
    } finally {
      setAcceptFixSubmitting(false)
    }
  }

  function openRejectFixModal(order: OrderSummary) {
    setRejectFixOrder(order)
    setRejectFixOutsourceNote(order.note_outsource || '')
  }

  async function handleRejectFix(e: React.FormEvent) {
    e.preventDefault()
    if (!rejectFixOrder) return
    setRejectFixSubmitting(true)
    try {
      await apiFetch(`/orders/${rejectFixOrder.id}/reject-fix-to-review`, {
        method: 'POST',
        body: JSON.stringify({
          note_outsource: rejectFixOutsourceNote,
        }),
      })
      showToast(`Đã từ chối Fix và gửi lại Review trên Web mẹ cho đơn ${rejectFixOrder.external_order_id}.`, 'success')
      markTabMoved(rejectFixOrder.id)
      setRejectFixOrder(null)
      await loadOrders()
    } catch (err: any) {
      showToast(err?.message || 'Không thể từ chối Fix.', 'error')
    } finally {
      setRejectFixSubmitting(false)
    }
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
      const targetOrders: OrderSummary[] = !isAdmin
        ? activeDesignerTab === 'doing'
          ? designerDoingOrders
          : activeDesignerTab === 'fix'
            ? designerFixOrders
            : activeDesignerTab === 'review'
              ? designerReviewOrders
              : activeDesignerTab === 'waiting_update'
                ? waitingUpdateOrders
                : activeDesignerTab === 'paid'
                  ? designerPaidOrders
                  : designerDoneOrders
        : adminTab === 'waiting'
          ? waitingOrders
          : adminTab === 'doing'
            ? doingOrders
            : adminTab === 'review'
              ? reviewOrders
              : adminTab === 'fix'
                ? filteredFixOrders
                : doneOrders

      const targetIds = targetOrders.map((o) => o.id)
      handleSyncPlatformStatus(targetIds.length > 0 ? targetIds : undefined)
    }
    window.addEventListener('request-sync-current-tab', handleRequestSync)
    return () => window.removeEventListener('request-sync-current-tab', handleRequestSync)
  }, [isAdmin, activeDesignerTab, designerDoingOrders, designerFixOrders, designerReviewOrders, waitingUpdateOrders, designerPaidOrders, designerDoneOrders, adminTab, waitingOrders, doingOrders, reviewOrders, fixOrders, doneOrders, orders])

  return (
    <DashboardLayout>
      {quickViewOrderId && (
        <ProductQuickViewModal
          orderId={quickViewOrderId}
          onClose={() => setQuickViewOrderId(null)}
        />
      )}
      {/* Image Zoom Modal */}
      <ImageModal
        isOpen={!!selectedImage}
        onClose={() => setSelectedImage(null)}
        imageUrl={selectedImage}
        hideExternalLink={!isAdmin}
      />

      {/* Admin 5 Sub-Tabs Navigation */}
      {isAdmin && (
        <div className="space-y-3">
          <div className="bg-white p-2 rounded-2xl border border-slate-200 shadow-xs flex flex-wrap items-center justify-between gap-3">
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 w-full lg:w-auto">
              {/* 1. WAITING TAB */}
              <button
                type="button"
                onClick={() => handleSwitchAdminTab('waiting')}
                className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center justify-center sm:justify-start gap-2 border ${adminTab === 'waiting'
                    ? 'bg-amber-500 text-white border-amber-500 shadow-xs ring-2 ring-amber-500/20'
                    : 'bg-amber-50/40 text-amber-900 border-amber-200/80 hover:bg-amber-100/60'
                  }`}
              >
                <Clock className="h-3.5 w-3.5" />
                <span>Waiting (Chờ chia)</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${adminTab === 'waiting' ? 'bg-white/25 text-white' : 'bg-amber-200/80 text-amber-900'
                    }`}
                >
                  {waitingOrders.length}
                </span>
              </button>

              {/* 2. DOING TAB */}
              <button
                type="button"
                onClick={() => handleSwitchAdminTab('doing')}
                className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center justify-center sm:justify-start gap-2 border ${adminTab === 'doing'
                    ? 'bg-[#0052CC] text-white border-[#0052CC] shadow-xs ring-2 ring-blue-500/20'
                    : 'bg-blue-50/40 text-blue-900 border-blue-200/80 hover:bg-blue-100/60'
                  }`}
              >
                <Layers className="h-3.5 w-3.5" />
                <span>Doing (Đang làm)</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${adminTab === 'doing' ? 'bg-white/25 text-white' : 'bg-blue-200/80 text-blue-900'
                    }`}
                >
                  {doingOrders.length}
                </span>
              </button>

              {/* 3. REVIEW TAB */}
              <button
                type="button"
                onClick={() => handleSwitchAdminTab('review')}
                className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center justify-center sm:justify-start gap-2 border ${adminTab === 'review'
                    ? 'bg-purple-600 text-white border-purple-600 shadow-xs ring-2 ring-purple-500/20'
                    : 'bg-purple-50/40 text-purple-900 border-purple-200/80 hover:bg-purple-100/60'
                  }`}
              >
                <Search className="h-3.5 w-3.5" />
                <span>Review (Chờ duyệt)</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${adminTab === 'review' ? 'bg-white/25 text-white' : 'bg-purple-200/80 text-purple-900'
                    }`}
                >
                  {reviewOrders.length}
                </span>
              </button>

              {/* 4. FIX TAB */}
              <button
                type="button"
                onClick={() => handleSwitchAdminTab('fix')}
                className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center justify-center sm:justify-start gap-2 border ${adminTab === 'fix'
                    ? 'bg-rose-600 text-white border-rose-600 shadow-xs ring-2 ring-rose-500/20'
                    : 'bg-rose-50/40 text-rose-900 border-rose-200/80 hover:bg-rose-100/60'
                  }`}
              >
                <AlertTriangle className="h-3.5 w-3.5" />
                <span>Fix (Cần sửa)</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${adminTab === 'fix' ? 'bg-white/25 text-white' : 'bg-rose-200/80 text-rose-900'
                    }`}
                >
                  {fixOrders.length}
                </span>
              </button>

              {/* 5. DONE TAB */}
              <button
                type="button"
                onClick={() => handleSwitchAdminTab('done')}
                className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center justify-center sm:justify-start gap-2 border ${adminTab === 'done'
                    ? 'bg-emerald-600 text-white border-emerald-600 shadow-xs ring-2 ring-emerald-500/20'
                    : 'bg-emerald-50/40 text-emerald-900 border-emerald-200/80 hover:bg-emerald-100/60'
                  }`}
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>Done (Hoàn thành)</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${adminTab === 'done' ? 'bg-white/25 text-white' : 'bg-emerald-200/80 text-emerald-900'
                    }`}
                >
                  {doneOrders.length}
                </span>
              </button>
            </div>

            {/* Contextual Action Bar corresponding to active Tab */}
            <div className="flex items-center gap-2 flex-wrap w-full lg:w-auto justify-end">
              {adminTab === 'doing' && (
                <div className="flex items-center gap-2.5 flex-wrap">
                  {/* Sub-filter for Doing tab: All, Missing Template, Normal */}
                  <div className="inline-flex items-center p-0.5 bg-slate-100 rounded-xl border border-slate-200">
                    <button
                      type="button"
                      onClick={() => setAdminDoingSubFilter('all')}
                      className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${adminDoingSubFilter === 'all'
                          ? 'bg-white text-slate-900 shadow-2xs'
                          : 'text-slate-600 hover:text-slate-900'
                        }`}
                    >
                      <span>Tất cả</span>
                      <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${adminDoingSubFilter === 'all' ? 'bg-slate-200 text-slate-800' : 'bg-slate-200/80 text-slate-600'
                        }`}>
                        {doingOrders.length}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setAdminDoingSubFilter('missing')}
                      className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${adminDoingSubFilter === 'missing'
                          ? 'bg-amber-500 text-white shadow-2xs'
                          : 'text-amber-800 hover:text-amber-950'
                        }`}
                    >
                      <span>Thiếu Form / Term</span>
                      <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${adminDoingSubFilter === 'missing' ? 'bg-white/20 text-white' : 'bg-amber-100 text-amber-900'
                        }`}>
                        {missingTemplateDoingOrders.length}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setAdminDoingSubFilter('normal')}
                      className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${adminDoingSubFilter === 'normal'
                          ? 'bg-blue-600 text-white shadow-2xs'
                          : 'text-blue-800 hover:text-blue-950'
                        }`}
                    >
                      <span>Đang làm bình thường</span>
                      <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${adminDoingSubFilter === 'normal' ? 'bg-white/20 text-white' : 'bg-blue-100 text-blue-900'
                        }`}>
                        {normalDoingOrders.length}
                      </span>
                    </button>
                  </div>

                  {isAdmin && (
                    <button
                      type="button"
                      onClick={() => handleSyncPlatformStatus(doingOrders.map((o) => o.id))}
                      disabled={isTriggering || !!syncStatus?.is_running || doingOrders.length === 0}
                      className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl shadow-2xs transition-all cursor-pointer disabled:opacity-50"
                      title="Đồng bộ trạng thái các đơn đang làm trong tab Doing"
                    >
                      <RefreshCw className={`h-3.5 w-3.5 ${isTriggering || syncStatus?.is_running ? 'animate-spin' : ''}`} />
                      <span>Đồng bộ tab Doing ({doingOrders.length})</span>
                    </button>
                  )}
                </div>
              )}

              {adminTab === 'review' && (
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono font-semibold px-2.5 py-1.5 rounded-xl bg-purple-50 text-purple-700 border border-purple-200 inline-flex items-center gap-1.5 shadow-2xs">
                    <Clock className="h-3 w-3 text-purple-600" />
                    <span>Tự động sync: {Math.floor(reviewAutoSyncCountdown / 60)}:{(reviewAutoSyncCountdown % 60).toString().padStart(2, '0')}</span>
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      setReviewAutoSyncCountdown(300)
                      handleSyncPlatformStatus(reviewOrders.map((o) => o.id))
                    }}
                    disabled={isTriggering || !!syncStatus?.is_running || reviewOrders.length === 0}
                    className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-bold text-white bg-purple-600 hover:bg-purple-700 rounded-xl shadow-2xs transition-all cursor-pointer disabled:opacity-50"
                    title="Đồng bộ ngay trạng thái các đơn chờ duyệt trong tab Review"
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${isTriggering || syncStatus?.is_running ? 'animate-spin' : ''}`} />
                    <span>Đồng bộ tab Review ({reviewOrders.length})</span>
                  </button>
                </div>
              )}

              {adminTab === 'fix' && (
                <div className="flex items-center gap-2.5 flex-wrap">
                  {/* 3-State Sub-filter for Admin Fix tab */}
                  <div className="inline-flex items-center p-0.5 bg-slate-100 rounded-xl border border-slate-200">
                    <button
                      type="button"
                      onClick={() => setAdminFixSubFilter('all')}
                      className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${adminFixSubFilter === 'all'
                          ? 'bg-white text-slate-900 shadow-2xs'
                          : 'text-slate-600 hover:text-slate-900'
                        }`}
                    >
                      <span>Tất cả</span>
                      <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${adminFixSubFilter === 'all' ? 'bg-slate-200 text-slate-800' : 'bg-slate-200/80 text-slate-600'
                        }`}>
                        {fixOrders.length}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setAdminFixSubFilter('pending')}
                      className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${adminFixSubFilter === 'pending'
                          ? 'bg-amber-500 text-white shadow-2xs'
                          : 'text-amber-800 hover:text-amber-950'
                        }`}
                    >
                      <span>Chưa lựa chọn</span>
                      <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${adminFixSubFilter === 'pending' ? 'bg-white/20 text-white' : 'bg-amber-100 text-amber-900'
                        }`}>
                        {pendingFixOrders.length}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setAdminFixSubFilter('approved')}
                      className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${adminFixSubFilter === 'approved'
                          ? 'bg-emerald-600 text-white shadow-2xs'
                          : 'text-emerald-800 hover:text-emerald-950'
                        }`}
                    >
                      <span>Đã chấp nhận Fix</span>
                      <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${adminFixSubFilter === 'approved' ? 'bg-white/20 text-white' : 'bg-emerald-100 text-emerald-900'
                        }`}>
                        {approvedFixOrders.length}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setAdminFixSubFilter('rejected')}
                      className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all cursor-pointer flex items-center gap-1.5 ${adminFixSubFilter === 'rejected'
                          ? 'bg-purple-600 text-white shadow-2xs'
                          : 'text-purple-800 hover:text-purple-950'
                        }`}
                    >
                      <span>Đã từ chối Fix</span>
                      <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${adminFixSubFilter === 'rejected' ? 'bg-white/20 text-white' : 'bg-purple-100 text-purple-900'
                        }`}>
                        {rejectedFixOrders.length}
                      </span>
                    </button>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleSyncPlatformStatus(fixOrders.map((o) => o.id))}
                    disabled={isTriggering || !!syncStatus?.is_running || fixOrders.length === 0}
                    className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 rounded-xl shadow-2xs transition-all cursor-pointer disabled:opacity-50"
                    title="Đồng bộ trạng thái các đơn cần sửa trong tab Fix"
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${isTriggering || syncStatus?.is_running ? 'animate-spin' : ''}`} />
                    <span>Đồng bộ tab Fix ({fixOrders.length})</span>
                  </button>
                </div>
              )}

              {adminTab === 'done' && (
                <span className="text-xs text-slate-500 font-medium px-3 py-1.5 bg-slate-50 border border-slate-200 rounded-xl">
                  Tổng đơn hoàn thành: <strong className="font-bold text-emerald-700 font-mono">{doneOrders.length}</strong>
                </span>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Support 3 Sub-Tabs Navigation */}
      {isSupport && (
        <div className="space-y-3">
          <div className="bg-white p-2 rounded-2xl border border-slate-200 shadow-xs flex flex-wrap items-center justify-between gap-3">
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 w-full lg:w-auto">
              {/* 1. UNCHECKED ORDERS (CHƯA KIỂM TRA) */}
              <button
                type="button"
                onClick={() => handleSwitchSupportTab('all')}
                className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center justify-center sm:justify-start gap-2 border ${supportTab === 'all'
                    ? 'bg-amber-500 text-white border-amber-500 shadow-xs ring-2 ring-amber-500/20'
                    : 'bg-amber-50/40 text-amber-900 border-amber-200/80 hover:bg-amber-100/60'
                  }`}
              >
                <Clock className="h-3.5 w-3.5" />
                <span>Chưa kiểm tra</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${supportTab === 'all' ? 'bg-white/25 text-white' : 'bg-amber-200/80 text-amber-900'
                    }`}
                >
                  {supportUncheckedOrders.length}
                </span>
              </button>

              {/* 2. DUPLICATE ORDERS (TRÙNG LẶP) */}
              <button
                type="button"
                onClick={() => handleSwitchSupportTab('duplicate')}
                className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center justify-center sm:justify-start gap-2 border ${supportTab === 'duplicate'
                    ? 'bg-purple-600 text-white border-purple-600 shadow-xs ring-2 ring-purple-500/20'
                    : 'bg-purple-50/40 text-purple-900 border-purple-200/80 hover:bg-purple-100/60'
                  }`}
              >
                <Layers className="h-3.5 w-3.5" />
                <span>Trùng lặp</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${supportTab === 'duplicate' ? 'bg-white/25 text-white' : 'bg-purple-200/80 text-purple-900'
                    }`}
                >
                  {supportDuplicateOrders.length}
                </span>
              </button>

              {/* 3. NON-DUPLICATE ORDERS (KHÔNG TRÙNG LẶP) */}
              <button
                type="button"
                onClick={() => handleSwitchSupportTab('non_duplicate')}
                className={`px-4 py-2.5 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center justify-center sm:justify-start gap-2 border ${supportTab === 'non_duplicate'
                    ? 'bg-emerald-600 text-white border-emerald-600 shadow-xs ring-2 ring-emerald-500/20'
                    : 'bg-emerald-50/40 text-emerald-900 border-emerald-200/80 hover:bg-emerald-100/60'
                  }`}
              >
                <CheckCircle2 className="h-3.5 w-3.5" />
                <span>Không trùng lặp</span>
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-bold ${supportTab === 'non_duplicate' ? 'bg-white/25 text-white' : 'bg-emerald-200/80 text-emerald-900'
                    }`}
                >
                  {supportNonDuplicateOrders.length}
                </span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Designer Workflow Tabs (Only for Designer) */}
      {!isManager && (
        <div className="bg-white p-3 rounded-2xl border border-slate-200 shadow-2xs flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-2 overflow-x-auto w-full pb-1 sm:pb-0">
            <button
              type="button"
              onClick={() => setActiveDesignerTab('doing')}
              className={`px-3.5 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${activeDesignerTab === 'doing'
                  ? 'bg-blue-600 text-white border-blue-600 shadow-2xs'
                  : 'bg-blue-50/60 text-blue-900 border-blue-200 hover:bg-blue-100/70'
                }`}
            >
              <span>Đang làm</span>
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${activeDesignerTab === 'doing' ? 'bg-white/20 text-white' : 'bg-blue-200/80 text-blue-900'
                  }`}
              >
                {designerDoingOrders.length}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveDesignerTab('fix')}
              className={`px-3.5 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${activeDesignerTab === 'fix'
                  ? 'bg-rose-600 text-white border-rose-600 shadow-2xs'
                  : 'bg-rose-50/70 text-rose-800 border-rose-200 hover:bg-rose-100/70'
                }`}
            >
              <AlertTriangle className="h-3.5 w-3.5 text-rose-500" />
              <span>Cần Sửa Gấp (Fix)</span>
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${activeDesignerTab === 'fix' ? 'bg-white/20 text-white' : 'bg-rose-200/80 text-rose-900'
                  }`}
              >
                {designerFixOrders.length}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveDesignerTab('review')}
              className={`px-3.5 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${activeDesignerTab === 'review'
                  ? 'bg-purple-600 text-white border-purple-600 shadow-2xs'
                  : 'bg-purple-50/60 text-purple-900 border-purple-200 hover:bg-purple-100/70'
                }`}
            >
              <span>Chờ duyệt</span>
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${activeDesignerTab === 'review' ? 'bg-white/20 text-white' : 'bg-purple-200/80 text-purple-900'
                  }`}
              >
                {designerReviewOrders.length}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveDesignerTab('waiting_update')}
              className={`px-3.5 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${activeDesignerTab === 'waiting_update'
                  ? 'bg-amber-600 text-white border-amber-600 shadow-2xs'
                  : 'bg-amber-50/60 text-amber-800 border-amber-200 hover:bg-amber-100/70'
                }`}
            >
              <Flag className="h-3.5 w-3.5" />
              <span>Chờ Cập Nhật</span>
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${activeDesignerTab === 'waiting_update' ? 'bg-white/20 text-white' : 'bg-amber-200/80 text-amber-800'
                  }`}
              >
                {waitingUpdateOrders.length}
              </span>
            </button>

            <button
              type="button"
              onClick={() => setActiveDesignerTab('paid')}
              className={`px-3.5 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer flex items-center gap-2 border ${activeDesignerTab === 'paid'
                  ? 'bg-emerald-600 text-white border-emerald-600 shadow-2xs'
                  : 'bg-emerald-50/60 text-emerald-900 border-emerald-200 hover:bg-emerald-100/70'
                }`}
            >
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
              <span>Đã thanh toán</span>
              <span
                className={`px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold ${activeDesignerTab === 'paid' ? 'bg-white/20 text-white' : 'bg-emerald-200/80 text-emerald-900'
                  }`}
              >
                {designerPaidOrders.length}
              </span>
            </button>
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
              placeholder={isAdmin ? "Tìm theo Mã Đơn, Tên SP, DES..." : "Tìm theo Tên Sản Phẩm..."}
              className="w-full pl-10 pr-4 py-2 text-xs rounded-lg border border-slate-200 focus:outline-none focus:border-[#0052CC] bg-slate-50"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2.5 w-full md:w-auto">
            {/* Tacahu Status Filter */}
            <div className="flex items-center gap-1.5">
              <Filter className="h-3.5 w-3.5 text-slate-400" />
              <select
                className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC]"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                title="Lọc theo trạng thái Tacahu"
              >
                <option value="">Tất cả Trạng Thái</option>
                <option value="WAITING">Waiting (Chờ chia / Chờ phân công)</option>
                <option value="DOING">Doing (Đang thực hiện)</option>
                <option value="REVIEW">Review (Chờ duyệt / Nộp bài)</option>
                <option value="FIX">Fix (Yêu cầu sửa lại)</option>
                <option value="DONE">Done (Đã hoàn thành / Claim)</option>
                <option value="CANCELLED">Cancelled (Đã hủy)</option>
              </select>
            </div>

            {/* Web mẹ Status Filter (Admin only) */}
            {isAdmin && (
              <div className="flex items-center gap-1.5">
                <select
                  className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC] text-slate-700"
                  value={platformStatusFilter}
                  onChange={(e) => setPlatformStatusFilter(e.target.value)}
                  title="Lọc theo trạng thái trên Web mẹ"
                >
                  <option value="">Tất cả trạng thái Print</option>
                  <option value="waiting">Prin: Waiting</option>
                  <option value="doing">Prin: Doing</option>
                  <option value="review">Prin: Review</option>
                  <option value="fix">Prin: Fix</option>
                  <option value="confirm">Prin: Confirm</option>
                  <option value="done">Prin: Done</option>
                  <option value="cancel">Prin: Cancel</option>
                  <option value="unspecified">Prin: Chưa xác định (Trống)</option>
                </select>
              </div>
            )}

            {/* Filter by Designer (Admin only) */}
            {isAdmin && (
              <select
                className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC]"
                value={designerFilter}
                onChange={(e) => setDesignerFilter(e.target.value)}
              >
                <option value="">Tất cả DES</option>
                <option value="unassigned">Chưa phân công</option>
                {regularDesigners.map((u) => (
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

            {/* Button Lọc Đơn Đã Đồng Bộ Ảnh */}
            <button
              type="button"
              onClick={() => {
                setSyncedImagesFilter((prev) => !prev)
                setCurrentPage(1)
              }}
              className={`inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-2 rounded-lg border transition-all cursor-pointer ${syncedImagesFilter
                  ? 'bg-emerald-600 text-white border-emerald-700 shadow-2xs ring-2 ring-emerald-400/40'
                  : 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-emerald-50 hover:text-emerald-700 hover:border-emerald-300'
                }`}
              title="Lọc chỉ hiển thị các đơn đã đồng bộ đầy đủ ảnh để ưu tiên chia việc trước"
            >
              <Images className={`h-3.5 w-3.5 ${syncedImagesFilter ? 'text-white' : 'text-emerald-600'}`} />
              <span>Đơn đã đồng bộ ảnh</span>
              {syncedOrdersCount > 0 && (
                <span
                  className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${syncedImagesFilter
                      ? 'bg-white text-emerald-800'
                      : 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                    }`}
                >
                  {syncedOrdersCount}
                </span>
              )}
            </button>
          </div>
        </div>

        {/* Date Filter Bar (3 Options: Thời gian tab, Order At, Ngày tạo) */}
        <div className="pt-2 border-t border-slate-100 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 text-xs text-slate-500 font-semibold">
              <Calendar className="h-3.5 w-3.5 text-[#0052CC]" />
              <span>Lọc thời gian:</span>
            </div>

            {/* Select Date Column */}
            <select
              value={dateFilterType}
              onChange={(e) => setDateFilterType(e.target.value as any)}
              className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-slate-50 font-semibold focus:outline-none focus:border-[#0052CC] text-[#0052CC]"
            >
              <option value="status_changed_at">Thời Gian (Vào tab)</option>
              <option value="order_created_at_ext">Order At (Giờ đặt)</option>
              {isAdmin && <option value="created_at">Ngày tạo (crawl)</option>}
            </select>

            {/* Date Inputs (UTC+7) */}
            <div className="flex items-center gap-1.5">
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => {
                  setDateFrom(e.target.value)
                  setDatePreset('')
                }}
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-slate-50 font-mono text-slate-700 focus:outline-none focus:border-[#0052CC]"
                title="Từ ngày (UTC+7)"
              />
              <span className="text-slate-400 text-xs">→</span>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => {
                  setDateTo(e.target.value)
                  setDatePreset('')
                }}
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-slate-50 font-mono text-slate-700 focus:outline-none focus:border-[#0052CC]"
                title="Đến ngày (UTC+7)"
              />
            </div>

            {/* Quick Presets */}
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => applyDatePreset('today')}
                className={`px-2 py-1 text-[11px] font-semibold rounded-md transition-all cursor-pointer ${datePreset === 'today' ? 'bg-[#0052CC] text-white shadow-2xs' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
              >
                Hôm nay
              </button>
              <button
                type="button"
                onClick={() => applyDatePreset('yesterday')}
                className={`px-2 py-1 text-[11px] font-semibold rounded-md transition-all cursor-pointer ${datePreset === 'yesterday' ? 'bg-[#0052CC] text-white shadow-2xs' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
              >
                Hôm qua
              </button>
              <button
                type="button"
                onClick={() => applyDatePreset('7days')}
                className={`px-2 py-1 text-[11px] font-semibold rounded-md transition-all cursor-pointer ${datePreset === '7days' ? 'bg-[#0052CC] text-white shadow-2xs' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
              >
                7 ngày
              </button>
              <button
                type="button"
                onClick={() => applyDatePreset('this_month')}
                className={`px-2 py-1 text-[11px] font-semibold rounded-md transition-all cursor-pointer ${datePreset === 'this_month' ? 'bg-[#0052CC] text-white shadow-2xs' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                  }`}
              >
                Tháng này
              </button>
            </div>
          </div>

          {/* Reset All Filters Button */}
          {(statusFilter || platformStatusFilter || designerFilter || batchFilter || searchQuery || dateFrom || dateTo || syncedImagesFilter) && (
            <button
              type="button"
              onClick={handleResetFilters}
              className="inline-flex items-center gap-1 text-xs font-semibold text-rose-600 hover:text-rose-700 bg-rose-50 hover:bg-rose-100 px-3 py-1.5 rounded-lg transition-colors cursor-pointer"
            >
              <X className="h-3.5 w-3.5" />
              <span>Xóa bộ lọc</span>
            </button>
          )}
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

          <div className="flex items-center gap-3 flex-wrap">
            <button
              type="button"
              onClick={moveSelectedToDuplicateDomain}
              disabled={movingToDuplicateDomain}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-[#0052CC] bg-white hover:bg-slate-100 rounded-lg shadow-sm transition-all disabled:opacity-50 cursor-pointer"
              title="Đưa đơn vào board chung của Designer Trello"
            >
              {movingToDuplicateDomain ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Layers className="h-3.5 w-3.5" />}
              <span>Đưa vào Đơn trùng lặp</span>
            </button>

            <button
              type="button"
              onClick={() => openPlatformStatusModal(
                selectedOrderIds,
                `Cập nhật ${selectedOrderIds.length} đơn đã chọn`,
              )}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-[#0052CC] bg-white hover:bg-slate-100 rounded-lg shadow-sm transition-all cursor-pointer"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Đổi trạng thái Print</span>
            </button>

            {/* Select Internal Designer */}
            <select
              value={bulkDesignerId}
              onChange={(e) => {
                const desId = e.target.value
                setBulkDesignerId(desId)
                const desUser = usersList.find((u) => u.id === desId)
                if (desUser?.platform_designer_option) {
                  setBulkPlatformDesigner(desUser.platform_designer_option)
                }
              }}
              className="bg-white text-slate-800 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/30 focus:outline-none shadow-xs"
            >
              <option value="">-- Chọn Designer phân công --</option>
              {regularDesigners.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.full_name || u.username} ({u.role})
                </option>
              ))}
            </select>

            {/* Select Web mẹ Designer */}
            <select
              value={bulkPlatformDesigner}
              onChange={(e) => setBulkPlatformDesigner(e.target.value)}
              disabled={loadingPlatformOptions}
              className="bg-white text-slate-800 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/30 focus:outline-none shadow-xs disabled:opacity-60"
            >
              <option value={DEFAULT_PLATFORM_DES}>{DEFAULT_PLATFORM_DES} (Mặc định)</option>
              {platformDesigners.filter((d) => d !== DEFAULT_PLATFORM_DES).map((designer) => (
                <option key={designer} value={designer}>{designer}</option>
              ))}
            </select>

            {/* Select Web mẹ Status */}
            <select
              value={bulkPlatformStatus}
              onChange={(e) => setBulkPlatformStatus(e.target.value)}
              disabled={loadingPlatformOptions}
              className="bg-white text-slate-800 text-xs font-semibold px-3 py-1.5 rounded-lg border border-white/30 focus:outline-none shadow-xs disabled:opacity-60"
            >
              {(platformStatuses.length ? platformStatuses : ['Doing', 'Review', 'Fix', 'Done', 'Waiting']).map((status) => (
                <option key={status} value={status}>{status}</option>
              ))}
            </select>

            <button
              onClick={handleBulkAssign}
              disabled={!bulkDesignerId || bulkAssigning || loadingPlatformOptions}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 rounded-lg shadow-sm transition-all disabled:opacity-50 cursor-pointer"
            >
              {bulkAssigning ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <UserPlus className="h-3.5 w-3.5" />}
              <span>Phân công</span>
            </button>

            {isAdmin && (
              <button
                type="button"
                onClick={() => setDeleteConfirmModalOpen(true)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 rounded-lg shadow-sm transition-all cursor-pointer"
              >
                <Trash2 className="h-3.5 w-3.5" />
                <span>Xóa hoàn toàn ({selectedOrderIds.length})</span>
              </button>
            )}

            {isAdmin && adminTab === 'doing' && (
              <button
                type="button"
                onClick={() => handleRevokeAssignment(selectedOrderIds)}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-white bg-rose-700 hover:bg-rose-800 rounded-lg shadow-sm transition-all cursor-pointer"
                title="Hủy phân công các đơn đã chọn và trả về trạng thái Waiting"
              >
                <UserX className="h-3.5 w-3.5" />
                <span>Hủy chia đơn ({selectedOrderIds.length})</span>
              </button>
            )}

            <button
              onClick={() => {
                setSelectedOrderIds([])
                setLastSelectedIndex(null)
              }}
              className="text-xs text-white/80 hover:text-white underline px-2 cursor-pointer font-medium"
            >
              Bỏ chọn
            </button>
          </div>
        </div>
      )}

      {/* Bulk Action Bar (For Support when orders selected) */}
      {isSupport && selectedOrderIds.length > 0 && (
        <div className="bg-[#0052CC] text-white px-5 py-3 rounded-xl shadow-lg flex flex-wrap items-center justify-between gap-3 animate-in fade-in slide-in-from-top-2 border border-blue-400/30">
          <div className="flex items-center gap-2">
            <span className="bg-white/20 px-3 py-1 rounded-lg text-xs font-bold font-mono">
              Đã chọn {selectedOrderIds.length} đơn hàng
            </span>
          </div>

          <div className="flex items-center gap-3 flex-wrap">
            {supportTab !== 'duplicate' && (
              <button
                type="button"
                onClick={() => handleSetDuplicateStatus(selectedOrderIds, 'duplicate')}
                disabled={updatingDuplicateStatus}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-bold text-amber-950 bg-amber-400 hover:bg-amber-300 rounded-lg shadow-sm transition-all disabled:opacity-50 cursor-pointer"
                title="Đánh dấu các đơn đã chọn là Trùng lặp và đưa vào Trello"
              >
                {updatingDuplicateStatus ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Layers className="h-3.5 w-3.5" />}
                <span>Đánh dấu Trùng lặp ({selectedOrderIds.length})</span>
              </button>
            )}

            {supportTab !== 'non_duplicate' && (
              <button
                type="button"
                onClick={() => handleSetDuplicateStatus(selectedOrderIds, 'non_duplicate')}
                disabled={updatingDuplicateStatus}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg shadow-sm transition-all disabled:opacity-50 cursor-pointer"
                title="Đánh dấu các đơn đã chọn là Không trùng lặp"
              >
                {updatingDuplicateStatus ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
                <span>Đánh dấu Không trùng ({selectedOrderIds.length})</span>
              </button>
            )}

            {supportTab !== 'all' && (
              <button
                type="button"
                onClick={() => handleSetDuplicateStatus(selectedOrderIds, 'uncheck')}
                disabled={updatingDuplicateStatus}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-bold text-slate-800 bg-white hover:bg-slate-100 rounded-lg shadow-sm transition-all disabled:opacity-50 cursor-pointer"
                title="Chuyển về trạng thái Chưa kiểm tra"
              >
                {updatingDuplicateStatus ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
                <span>Chuyển về Chưa kiểm tra ({selectedOrderIds.length})</span>
              </button>
            )}

            <button
              type="button"
              onClick={() => {
                setSelectedOrderIds([])
                setLastSelectedIndex(null)
              }}
              className="text-xs text-white/80 hover:text-white underline px-2 cursor-pointer font-medium"
            >
              Bỏ chọn
            </button>
          </div>
        </div>
      )}

      {/* Table Task Counter / Summary Bar (Placed right between filters and table) */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-1 py-0.5">
        <div className="flex items-center gap-2.5 flex-wrap">
          <div className="inline-flex items-center gap-2 bg-white px-3 py-1.5 rounded-lg border border-slate-200/80 shadow-2xs">
            <span className="text-xs font-semibold text-slate-600">Tổng số task:</span>
            <span className="inline-flex items-center justify-center font-mono text-sm font-extrabold text-[#0052CC] bg-blue-50 px-2 py-0.5 rounded-md border border-blue-200/70 shadow-2xs min-w-[28px]">
              {filteredOrders.length}
            </span>
            <span className="text-xs text-slate-500 font-medium">task</span>
          </div>

          {(searchQuery || statusFilter || platformStatusFilter || designerFilter || batchFilter || dateFrom || dateTo || syncedImagesFilter) && (
            <div className="inline-flex items-center gap-1.5 text-xs text-slate-500 bg-slate-100/80 px-2.5 py-1 rounded-md border border-slate-200/60">
              <span className="text-slate-400">Đang lọc từ:</span>
              <span className="font-mono font-bold text-slate-700">{baseOrders.length}</span>
              <span>task trong tab</span>
              {syncedImagesFilter && (
                <span className="inline-flex items-center gap-1 ml-1 px-1.5 py-0.2 rounded bg-emerald-100 text-emerald-800 text-[10px] font-bold">
                  <Images className="h-2.5 w-2.5" />
                  Đã đồng bộ ảnh
                </span>
              )}
            </div>
          )}
        </div>

        {filteredOrders.length > 0 && (
          <div className="text-xs text-slate-500 font-medium flex items-center gap-1">
            <span>Hiển thị:</span>
            <span className="font-mono font-bold text-slate-700">
              {Math.min((currentPage - 1) * 100 + 1, filteredOrders.length)}–{Math.min(currentPage * 100, filteredOrders.length)}
            </span>
            <span className="text-slate-400">/</span>
            <span className="font-mono font-bold text-slate-700">{filteredOrders.length}</span>
          </div>
        )}
      </div>

      {/* Row-based Data Table UI */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-white shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              {isSupport ? (
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500 tracking-wider">
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
                  <th className="py-3 px-3 w-28 text-center">Ảnh</th>
                  <th className="py-3 px-4">Thông Tin Đơn Hàng</th>
                  <th className="py-3 px-4 text-right w-72">Phân Loại / Thao Tác</th>
                </tr>
              ) : isAdmin ? (
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500 tracking-wider">
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
                  <th className="py-3 px-3 w-28 text-center">Ảnh</th>
                  <th className="py-3 px-4">Mã Đơn</th>
                  <th className="py-3 px-4">Trạng Thái</th>
                  <th className="py-3 px-4">Des Đảm Nhận</th>
                  <th className="py-3 px-4 whitespace-nowrap">
                    <button type="button" onClick={() => toggleDateSort('status_changed_at')} className="inline-flex items-center gap-1 hover:text-[#0052CC]" title="Sắp xếp theo thời gian chuyển vào tab (UTC+7)">
                      Thời Gian <ArrowDownUp className={`h-3.5 w-3.5 ${dateSort.field === 'status_changed_at' ? 'text-[#0052CC]' : ''}`} />
                    </button>
                  </th>
                  <th className="py-3 px-4 whitespace-nowrap">
                    <button type="button" onClick={() => toggleDateSort('order_created_at_ext')} className="inline-flex items-center gap-1 hover:text-[#0052CC]" title="Sắp xếp theo Order at">
                      Order At <ArrowDownUp className={`h-3.5 w-3.5 ${dateSort.field === 'order_created_at_ext' ? 'text-[#0052CC]' : ''}`} />
                    </button>
                  </th>
                  <th className="py-3 px-4 whitespace-nowrap">
                    <button type="button" onClick={() => toggleDateSort('created_at')} className="inline-flex items-center gap-1 hover:text-[#0052CC]" title="Sắp xếp theo ngày tạo (crawl)">
                      Ngày tạo (crawl) <ArrowDownUp className={`h-3.5 w-3.5 ${dateSort.field === 'created_at' ? 'text-[#0052CC]' : ''}`} />
                    </button>
                  </th>
                  <th className="py-3 px-4 text-right">Thao Tác</th>
                </tr>
              ) : (
                <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500 tracking-wider">
                  <th className="py-3 px-3 w-28 text-center">Ảnh</th>
                  <th className="py-3 px-4 min-w-[220px]">Tên Sản Phẩm (Click để copy)</th>
                  <th className="py-3 px-4 w-52">Trạng Thái &amp; Ghi Chú</th>
                  <th className="py-3 px-4 w-36 whitespace-nowrap">
                    <button type="button" onClick={() => toggleDateSort('status_changed_at')} className="inline-flex items-center gap-1 hover:text-[#0052CC]" title="Sắp xếp theo thời gian chuyển vào tab (UTC+7)">
                      Thời Gian <ArrowDownUp className={`h-3.5 w-3.5 ${dateSort.field === 'status_changed_at' ? 'text-[#0052CC]' : ''}`} />
                    </button>
                  </th>
                  {activeDesignerTab === 'doing' && (
                    <th className="py-3 px-4 min-w-[320px]">Nộp Link Bài Thiết Kế</th>
                  )}
                </tr>
              )}
            </thead>
            <tbody className="divide-y divide-slate-100 text-xs">
              {paginatedOrders.length === 0 ? (
                <tr>
                  <td colSpan={isSupport ? 4 : isAdmin ? 9 : 5} className="py-12 text-center text-slate-400">
                    {ordersLoading ? (
                      <>
                        <Loader2 className="h-8 w-8 mx-auto mb-2 animate-spin opacity-50 text-[#0052CC]" />
                        <p className="font-medium text-sm text-slate-500">Đang cập nhật danh sách đơn…</p>
                      </>
                    ) : (
                      <>
                        <Package className="h-10 w-10 mx-auto mb-2 opacity-30 text-slate-400" />
                        <p className="font-medium text-sm text-slate-500">Không có đơn hàng nào trong tab này</p>
                        <p className="text-xs text-slate-400 mt-1">
                          Đơn hàng sẽ xuất hiện khi có sự thay đổi trạng thái hoặc quét đơn từ Web mẹ
                        </p>
                      </>
                    )}
                  </td>
                </tr>
              ) : (
                paginatedOrders.map((o, idx) => {
                  const isSelected = selectedOrderIds.includes(o.id)
                  const isHighlighted = newlyCrawledOrderIds.includes(o.id) || recentTabMovedOrderIds.includes(o.id)

                  return (
                    <tr
                      key={o.id}
                      onClick={() => {
                        dismissHighlight(o.id)
                        if (isAdmin) {
                          navigate(`/orders/${o.id}`)
                        } else {
                          setQuickViewOrderId(o.id)
                        }
                      }}
                      className={`transition-all duration-150 cursor-pointer ${isHighlighted
                          ? 'bg-emerald-50/80 border-l-4 border-l-emerald-500 shadow-xs'
                          : isSelected
                            ? 'bg-blue-50/80 font-medium'
                            : 'hover:bg-blue-50/60'
                        }`}
                      title={isAdmin ? 'Click vào dòng để xem chi tiết đơn hàng' : 'Click vào dòng để xem nhanh sản phẩm'}
                    >
                      {isSupport ? (
                        <>
                          {/* 1. Support Checkbox */}
                          <td className="py-3 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onClick={(e) => {
                                if (e.shiftKey && lastSelectedIndex !== null) {
                                  const start = Math.min(lastSelectedIndex, idx)
                                  const end = Math.max(lastSelectedIndex, idx)
                                  const rangeIds = paginatedOrders.slice(start, end + 1).map((item) => item.id)
                                  setSelectedOrderIds((prev) => Array.from(new Set([...prev, ...rangeIds])))
                                } else {
                                  setSelectedOrderIds((prev) =>
                                    prev.includes(o.id) ? prev.filter((id) => id !== o.id) : [...prev, o.id]
                                  )
                                  setLastSelectedIndex(idx)
                                }
                              }}
                              onChange={() => { }}
                              className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] h-3.5 w-3.5 cursor-pointer"
                            />
                          </td>

                          {/* 2. Support Image Preview */}
                          <td className="py-3 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                            {o.thumbnail_url ? (
                              <img
                                src={resolveAssetUrl(o.thumbnail_url)}
                                alt={o.external_order_id}
                                title="Click để xem ảnh phóng to"
                                onClick={() => setSelectedImage(resolveAssetUrl(o.thumbnail_url) ?? null)}
                                className="h-20 w-20 rounded-xl object-cover border border-slate-200 mx-auto shadow-xs cursor-pointer hover:scale-105 transition-transform hover:ring-2 hover:ring-[#0052CC]"
                              />
                            ) : (
                              <div className="h-20 w-20 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
                                <Package className="h-7 w-7" />
                              </div>
                            )}
                          </td>

                          {/* 3. Support Order Info (Mã Đơn, Tên Đơn, Bộ Ảnh, Template) */}
                          <td className="py-3 px-4">
                            <div className="space-y-1.5">
                              <div className="flex items-center gap-2 flex-wrap">
                                <CopyableOrderCode code={o.external_order_id} />
                                {o.template_missing && (
                                  <span className="inline-flex items-center gap-1 rounded border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[10px] font-bold text-rose-700">
                                    <Flag className="h-2.5 w-2.5" />
                                    Thiếu template
                                  </span>
                                )}
                              </div>

                              {o.product_name && (
                                <p className="text-xs text-slate-800 font-semibold line-clamp-2" title={o.product_name}>
                                  {o.product_name}
                                </p>
                              )}

                              {/* Badges: Bộ Ảnh, Template, SKU */}
                              <div className="flex items-center gap-2 pt-0.5 flex-wrap" onClick={(e) => e.stopPropagation()}>
                                {(() => {
                                  const dbCount =
                                    o.product_image_urls && o.product_image_urls.length > 0
                                      ? o.product_image_urls.length
                                      : o.thumbnail_url
                                        ? 1
                                        : 0
                                  const liveStatus = syncStatusMap[o.id]
                                  const imgCount =
                                    liveStatus?.status === 'success' && typeof liveStatus?.count === 'number'
                                      ? Math.max(liveStatus.count, dbCount)
                                      : dbCount
                                  return (
                                    <span
                                      className={`inline-flex items-center gap-1 text-[11px] font-bold px-2 py-0.5 rounded-md border shadow-2xs ${imgCount > 1
                                          ? 'text-emerald-700 bg-emerald-50 border-emerald-200'
                                          : 'text-amber-800 bg-amber-50 border-amber-200'
                                        }`}
                                      title={`Bộ ảnh sản phẩm: ${imgCount} ảnh`}
                                    >
                                      <Images className="h-3 w-3" />
                                      <span>{imgCount} ảnh</span>
                                    </span>
                                  )
                                })()}

                                {o.source_files && o.source_files.length > 0 && (
                                  <span className="inline-flex items-center gap-1 text-[11px] font-bold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-md">
                                    <Layers className="h-3 w-3" />
                                    <span>{o.source_files.length} template file</span>
                                  </span>
                                )}

                                {o.sku_image_url && (
                                  <a
                                    href={o.sku_image_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-[11px] font-bold text-[#0052CC] hover:underline inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-blue-50 border border-blue-100"
                                    title="Xem ảnh SKU Print"
                                  >
                                    <span>Ảnh SKU</span>
                                    <ExternalLink className="h-2.5 w-2.5" />
                                  </a>
                                )}
                              </div>
                            </div>
                          </td>

                          {/* 4. Support Actions: 2 Buttons in Tab 1 OR Tag with 'X' in Tabs 2 & 3 */}
                          <td className="py-3 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                            <div className="flex items-center justify-end gap-2">
                              {supportTab === 'all' && (
                                <>
                                  <button
                                    type="button"
                                    onClick={() => handleSetDuplicateStatus([o.id], 'duplicate')}
                                    disabled={updatingDuplicateStatus}
                                    className="inline-flex items-center gap-1.5 text-xs font-bold text-amber-900 bg-amber-100 hover:bg-amber-200 border border-amber-300 px-3 py-1.5 rounded-lg transition-all cursor-pointer shadow-2xs hover:scale-105 active:scale-95 disabled:opacity-50"
                                    title="Đánh dấu đơn này là Trùng lặp"
                                  >
                                    <Layers className="h-3.5 w-3.5 text-amber-700" />
                                    <span>Trùng lặp</span>
                                  </button>

                                  <button
                                    type="button"
                                    onClick={() => handleSetDuplicateStatus([o.id], 'non_duplicate')}
                                    disabled={updatingDuplicateStatus}
                                    className="inline-flex items-center gap-1.5 text-xs font-bold text-emerald-900 bg-emerald-100 hover:bg-emerald-200 border border-emerald-300 px-3 py-1.5 rounded-lg transition-all cursor-pointer shadow-2xs hover:scale-105 active:scale-95 disabled:opacity-50"
                                    title="Đánh dấu đơn này là Không trùng lặp"
                                  >
                                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-700" />
                                    <span>Không trùng lặp</span>
                                  </button>
                                </>
                              )}

                              {supportTab === 'duplicate' && (
                                <div className="inline-flex items-center gap-1.5 rounded-lg bg-purple-100 border border-purple-300 px-3 py-1.5 text-xs font-bold text-purple-900 shadow-2xs group">
                                  <Layers className="h-3.5 w-3.5 text-purple-700" />
                                  <span>Trùng lặp</span>
                                  <button
                                    type="button"
                                    onClick={() => handleSetDuplicateStatus([o.id], 'uncheck')}
                                    disabled={updatingDuplicateStatus}
                                    className="ml-1 p-0.5 rounded-full hover:bg-purple-200 text-purple-700 hover:text-purple-950 transition-all cursor-pointer hover:scale-110"
                                    title="Hủy tag Trùng lặp (quay lại tab Chưa kiểm tra)"
                                  >
                                    <X className="h-3.5 w-3.5 stroke-[2.5]" />
                                  </button>
                                </div>
                              )}

                              {supportTab === 'non_duplicate' && (
                                <div className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-100 border border-emerald-300 px-3 py-1.5 text-xs font-bold text-emerald-900 shadow-2xs group">
                                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-700" />
                                  <span>Không trùng lặp</span>
                                  <button
                                    type="button"
                                    onClick={() => handleSetDuplicateStatus([o.id], 'uncheck')}
                                    disabled={updatingDuplicateStatus}
                                    className="ml-1 p-0.5 rounded-full hover:bg-emerald-200 text-emerald-700 hover:text-emerald-950 transition-all cursor-pointer hover:scale-110"
                                    title="Hủy tag Không trùng lặp (quay lại tab Chưa kiểm tra)"
                                  >
                                    <X className="h-3.5 w-3.5 stroke-[2.5]" />
                                  </button>
                                </div>
                              )}
                            </div>
                          </td>
                        </>
                      ) : isAdmin ? (
                        <>
                          <td className="py-2.5 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                            <input
                              type="checkbox"
                              checked={isSelected}
                              onClick={(e) => {
                                if (e.shiftKey && lastSelectedIndex !== null) {
                                  const start = Math.min(lastSelectedIndex, idx)
                                  const end = Math.max(lastSelectedIndex, idx)
                                  const rangeIds = paginatedOrders.slice(start, end + 1).map((item) => item.id)
                                  setSelectedOrderIds((prev) => Array.from(new Set([...prev, ...rangeIds])))
                                } else {
                                  setSelectedOrderIds((prev) =>
                                    prev.includes(o.id) ? prev.filter((id) => id !== o.id) : [...prev, o.id]
                                  )
                                  setLastSelectedIndex(idx)
                                }
                              }}
                              onChange={() => { }}
                              className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] h-3.5 w-3.5 cursor-pointer"
                            />
                          </td>

                          {/* Image Thumbnail with Click-to-Zoom */}
                          <td className="py-2.5 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                            {o.thumbnail_url ? (
                              <img
                                src={resolveAssetUrl(o.thumbnail_url)}
                                alt={o.external_order_id}
                                title="Click để xem ảnh phóng to"
                                onClick={() => setSelectedImage(resolveAssetUrl(o.thumbnail_url) ?? null)}
                                className="h-20 w-20 rounded-xl object-cover border border-slate-200 mx-auto shadow-xs cursor-pointer hover:scale-105 transition-transform hover:ring-2 hover:ring-[#0052CC]"
                              />
                            ) : (
                              <div className="h-20 w-20 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
                                <Package className="h-7 w-7" />
                              </div>
                            )}
                          </td>

                          {/* Order Code / Product Name */}
                          <td className="py-2.5 px-4 font-semibold text-[#0052CC]">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              <CopyableOrderCode code={o.external_order_id} />

                              {/* Admin: Orange exclamation mark if NOT checked by support across ALL tabs */}
                              {(!o.duplicate_check_status || o.duplicate_check_status === 'uncheck') && (
                                <span
                                  className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-900 shadow-2xs"
                                  title="Support team chưa kiểm tra trùng lặp cho đơn này"
                                >
                                  <AlertTriangle className="h-3 w-3 text-amber-600 shrink-0" />
                                  <span>Chưa kiểm tra</span>
                                </span>
                              )}

                              {o.work_domain === 'duplicate' && (
                                <span className="inline-flex rounded border border-violet-200 bg-violet-50 px-1.5 py-0.2 text-[10px] font-bold text-violet-700">
                                  Đơn trùng
                                </span>
                              )}
                              {o.template_missing && (
                                <span className="inline-flex rounded border border-rose-200 bg-rose-50 px-1.5 py-0.2 text-[10px] font-bold text-rose-700">Thiếu temp</span>
                              )}
                            </div>

                            {o.product_name && (
                              <p className="text-[11px] text-slate-500 font-normal line-clamp-1 mt-0.5" title={o.product_name}>
                                {o.product_name}
                              </p>
                            )}

                            {/* Badges and links */}
                            <div className="flex items-center gap-2 mt-1 flex-wrap" onClick={(e) => e.stopPropagation()}>
                              {o.sku_image_url && (
                                <a
                                  href={o.sku_image_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="text-[10px] font-bold text-[#0052CC] hover:underline inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-blue-50 border border-blue-100"
                                  title="Xem ảnh SKU Print"
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
                                  title="Mở đơn trên Web mẹ"
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

                              {/* Image Count & Sync Status Badge */}
                              {(() => {
                                const dbCount =
                                  o.product_image_urls && o.product_image_urls.length > 0
                                    ? o.product_image_urls.length
                                    : o.thumbnail_url
                                      ? 1
                                      : 0
                                const liveStatus = syncStatusMap[o.id]
                                const imgCount =
                                  liveStatus?.status === 'success' && typeof liveStatus?.count === 'number'
                                    ? Math.max(liveStatus.count, dbCount)
                                    : dbCount
                                const isSynced = imgCount > 1
                                return isSynced ? (
                                  <span
                                    className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200 shadow-2xs"
                                    title={`Đã đồng bộ đủ bộ ảnh (${imgCount} ảnh)`}
                                  >
                                    <span>{imgCount} ảnh</span>
                                    <Check className="h-3 w-3 text-emerald-600 stroke-[3]" />
                                  </span>
                                ) : (
                                  <span
                                    className="inline-flex items-center gap-1 text-[10px] font-bold text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200 shadow-2xs"
                                    title={`Chưa đồng bộ bộ ảnh (${imgCount || 1} ảnh)`}
                                  >
                                    <span>{imgCount || 1} ảnh</span>
                                  </span>
                                )
                              })()}
                            </div>

                            {/* Note Outsource preview for Fix orders */}
                            {o.state === 'REVISION' && o.note_outsource && (
                              <div className="mt-1.5 p-2 rounded-lg bg-orange-50 border border-orange-200 text-[11px] text-orange-950 font-normal">
                                <div className="font-bold flex items-center gap-1 text-orange-900 mb-0.5">
                                  <AlertTriangle className="h-3 w-3 text-orange-600 shrink-0" />
                                  <span>QC Acc Mẹ:</span>
                                </div>
                                <div className="whitespace-pre-wrap break-all leading-tight text-slate-800 line-clamp-2">
                                  <LinkifiedText text={o.note_outsource} />
                                </div>
                              </div>
                            )}
                          </td>

                          {/* Status Column: Dropdown for Admin */}
                          <td className="py-2.5 px-4" onClick={(e) => e.stopPropagation()}>
                            <StatusDropdown
                              orderId={o.id}
                              externalOrderId={o.external_order_id}
                              currentState={o.state}
                              disabled={Boolean(o.template_missing)}
                              onStatusChanged={(newState) => {
                                markTabMoved(o.id)
                                setOrders((prev) =>
                                  prev.map((item) => (item.id === o.id ? { ...item, state: newState } : item))
                                )
                              }}
                            />
                            {o.platform_status && (
                              <div className="mt-1 text-[10px] font-mono text-slate-400 flex items-center gap-1">
                                <span>Prin:</span>
                                <span className="font-semibold text-slate-600 inline-flex items-center gap-1">
                                  {recentPlatformChanges[o.id]?.statusChanged && (Date.now() - (recentPlatformChanges[o.id]?.timestamp || 0) < 300000) && (
                                    <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse shadow-xs shrink-0" title="Trạng thái Web mẹ mới cập nhật (hiển thị 5 phút hoặc khi click)" />
                                  )}
                                  <span>{o.platform_status}</span>
                                </span>
                              </div>
                            )}
                          </td>

                          {/* DES Đảm Nhận */}
                          <td className="py-2.5 px-4 font-medium text-slate-700" onClick={(e) => e.stopPropagation()}>
                            {o.assigned_designer_name ? (
                              <span
                                onClick={() => openAssignModal(o)}
                                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-blue-50 text-[#0052CC] font-semibold text-xs cursor-pointer hover:bg-blue-100 hover:scale-105 transition-all"
                                title="Click để đổi Designer đảm nhận"
                              >
                                <User className="h-3 w-3" />
                                <span>{o.assigned_designer_name}</span>
                              </span>
                            ) : (
                              <span
                                onClick={() => openAssignModal(o)}
                                className="text-slate-400 font-normal text-xs cursor-pointer hover:text-[#0052CC] hover:underline font-semibold"
                                title="Click để phân công Designer"
                              >
                                + Phân công
                              </span>
                            )}
                            {(o.platform_designer || o.platform_assignment_lifecycle === 'pending') && (
                              <div className="mt-0.5 text-[10px] font-medium text-slate-500 flex items-center gap-1 max-w-[160px] truncate" title={o.platform_designer || ''}>
                                <span>Prin:</span>
                                <span className="inline-flex items-center gap-1 truncate">
                                  {recentPlatformChanges[o.id]?.designerChanged && (Date.now() - (recentPlatformChanges[o.id]?.timestamp || 0) < 300000) && (
                                    <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse shadow-xs shrink-0" title="Designer Print mới cập nhật (hiển thị 5 phút hoặc khi click)" />
                                  )}
                                  <span className="truncate">{o.platform_designer || '—'}</span>
                                </span>
                                {o.platform_assignment_lifecycle === 'pending' && (
                                  <Loader2 className="h-2.5 w-2.5 animate-spin inline-block ml-1 text-[#0052CC]" />
                                )}
                              </div>
                            )}
                          </td>

                          {/* Thời Gian (Vào Tab UTC+7) */}
                          <td className="py-2.5 px-4 whitespace-nowrap">
                            {(() => {
                              const split = formatUtc7Split(o.status_changed_at)
                              if (!split) return <span className="text-slate-300 font-mono text-xs">-</span>
                              return (
                                <div className="flex flex-col leading-tight" title="Thời gian chuyển vào tab / trạng thái gần nhất (UTC+7)">
                                  <span className="font-mono text-xs font-bold text-slate-800">{split.time}</span>
                                  <span className="font-mono text-[11px] text-slate-500">{split.date}</span>
                                </div>
                              )
                            })()}
                          </td>

                          {/* Web mẹ Order Created At (Order At) */}
                          <td className="py-2.5 px-4 whitespace-nowrap">
                            {(() => {
                              const split = formatUtc7Split(o.order_created_at_ext)
                              if (!split) return <span className="text-slate-300 font-mono text-xs">-</span>
                              return (
                                <div className="flex flex-col leading-tight" title="Thời gian khách đặt hàng (Order at)">
                                  <span className="font-mono text-xs font-semibold text-slate-700">{split.time}</span>
                                  <span className="font-mono text-[11px] text-slate-400">{split.date}</span>
                                </div>
                              )
                            })()}
                          </td>

                          {/* Created At (Tacahu Import Time) */}
                          <td className="py-2.5 px-4 whitespace-nowrap">
                            {(() => {
                              const split = formatUtc7Split(o.created_at)
                              if (!split) return <span className="text-slate-300 font-mono text-xs">-</span>
                              return (
                                <div className="flex flex-col leading-tight" title="Thời gian tạo trong Tacahu">
                                  <span className="font-mono text-xs font-medium text-slate-600">{split.time}</span>
                                  <span className="font-mono text-[11px] text-slate-400">{split.date}</span>
                                </div>
                              )
                            })()}
                          </td>

                          {/* Actions Contextual to Active Tab */}
                          <td className="py-2.5 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                            <div className="flex items-center justify-end gap-1.5 flex-wrap">
                              {/* Doing Tab Action: Revoke Assignment for Admin */}
                              {adminTab === 'doing' && (
                                <button
                                  type="button"
                                  onClick={() => handleRevokeAssignment([o.id])}
                                  className="inline-flex items-center gap-1 text-xs font-bold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 px-2.5 py-1 rounded-lg transition-colors cursor-pointer shadow-2xs"
                                  title="Hủy phân công đơn này (trả về trạng thái Waiting)"
                                >
                                  <UserX className="h-3 w-3 text-rose-600" />
                                  <span>Hủy chia</span>
                                </button>
                              )}

                              {/* Fix Tab Actions: Accept Fix (Chấp nhận & giao Des) OR Reject Fix (Từ chối & gửi lại Review) */}
                              {adminTab === 'fix' && (
                                <>
                                  {o.fix_approved_by_admin ? (
                                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 shadow-2xs">
                                      <Check className="h-3.5 w-3.5 text-emerald-600" />
                                      <span>Đã gửi fix cho des</span>
                                    </span>
                                  ) : o.fix_rejected_by_admin ? (
                                    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold bg-purple-50 text-purple-700 border border-purple-200 shadow-2xs">
                                      <Undo2 className="h-3.5 w-3.5 text-purple-600" />
                                      <span>Đã từ chối fix</span>
                                    </span>
                                  ) : (
                                    <>
                                      <button
                                        type="button"
                                        onClick={() => openAcceptFixModal(o)}
                                        className="inline-flex items-center gap-1 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 px-2.5 py-1 rounded-lg transition-colors cursor-pointer shadow-2xs"
                                        title="Chấp nhận yêu cầu Fix và giao bài cho Designer"
                                      >
                                        <UserPlus className="h-3 w-3" />
                                        <span>Chấp nhận Fix</span>
                                      </button>
                                      <button
                                        type="button"
                                        onClick={() => openRejectFixModal(o)}
                                        className="inline-flex items-center gap-1 text-xs font-bold text-white bg-purple-600 hover:bg-purple-700 px-2.5 py-1 rounded-lg transition-colors cursor-pointer shadow-2xs"
                                        title="Từ chối Fix và gửi lại Review trên Web mẹ"
                                      >
                                        <Undo2 className="h-3 w-3" />
                                        <span>Từ chối Fix</span>
                                      </button>
                                    </>
                                  )}
                                </>
                              )}

                              {/* Order Details Link */}
                              <Link
                                to={`/orders/${o.id}`}
                                className="inline-flex items-center gap-0.5 text-xs font-semibold text-[#0052CC] hover:text-[#003D99] hover:bg-blue-50 px-2.5 py-1 rounded-md transition-colors"
                              >
                                <span>Chi tiết</span>
                                <ChevronRight className="h-3.5 w-3.5" />
                              </Link>
                            </div>
                          </td>
                        </>
                      ) : (
                        /* Designer View: Clean, basic info + Click-to-copy Product Name + Inline Link Submission */
                        <>
                          {/* 1. Thumbnail */}
                          <td className="py-3 px-3 text-center" onClick={(e) => e.stopPropagation()}>
                            {o.thumbnail_url ? (
                              <img
                                src={resolveAssetUrl(o.thumbnail_url)}
                                alt={o.product_name || 'Đơn thiết kế'}
                                title="Click để xem ảnh phóng to"
                                onClick={() => setSelectedImage(resolveAssetUrl(o.thumbnail_url) ?? null)}
                                className="h-20 w-20 rounded-xl object-cover border border-slate-200 mx-auto shadow-xs cursor-pointer hover:scale-105 transition-transform hover:ring-2 hover:ring-[#0052CC]"
                              />
                            ) : (
                              <div className="h-20 w-20 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
                                <Package className="h-7 w-7" />
                              </div>
                            )}
                          </td>

                          {/* 2. Tên Sản Phẩm (Click để copy) + Xem chi tiết quick link */}
                          <td className="py-3 px-4">
                            <div className="space-y-1.5">
                              <div className="flex items-start gap-1.5 flex-wrap">
                                <CopyableProductName name={o.product_name || o.external_order_id} textSize="text-xs font-bold" />
                                {o.template_missing && (
                                  <span className="inline-flex rounded border border-rose-200 bg-rose-50 px-1.5 py-0.5 text-[10px] font-bold text-rose-700 shrink-0">
                                    Thiếu temp
                                  </span>
                                )}
                                {o.work_domain === 'duplicate' && (
                                  <span className="inline-flex rounded border border-violet-200 bg-violet-50 px-1.5 py-0.5 text-[10px] font-bold text-violet-700 shrink-0">
                                    Đơn trùng
                                  </span>
                                )}
                              </div>

                              {/* Badges and Quick details link */}
                              <div className="flex items-center gap-2 pt-0.5 flex-wrap" onClick={(e) => e.stopPropagation()}>
                                <Link
                                  to={`/orders/${o.id}`}
                                  onClick={() => dismissHighlight(o.id)}
                                  className="inline-flex items-center gap-1 text-[11px] font-bold text-[#0052CC] hover:text-[#003D99] hover:underline bg-blue-50/80 border border-blue-100 px-2 py-0.5 rounded transition-colors"
                                  title="Xem toàn bộ thông tin chi tiết của đơn hàng"
                                >
                                  <span>Xem chi tiết</span>
                                  <ChevronRight className="h-3 w-3" />
                                </Link>

                                {o.sku_image_url && (
                                  <a
                                    href={o.sku_image_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-[10px] font-bold text-[#0052CC] hover:underline inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-blue-50 border border-blue-100"
                                    title="Xem ảnh SKU Print"
                                  >
                                    <span>Ảnh SKU</span>
                                    <ExternalLink className="h-2.5 w-2.5" />
                                  </a>
                                )}

                                {o.source_files && o.source_files.length > 0 && (
                                  <span className="text-[10px] font-bold text-slate-600 px-1.5 py-0.5 rounded bg-slate-100 border border-slate-200">
                                    {o.source_files.length} file source
                                  </span>
                                )}
                              </div>
                            </div>
                          </td>

                          {/* 3. Trạng Thái & Ghi Chú */}
                          <td className="py-3 px-4" onClick={(e) => e.stopPropagation()}>
                            <div className="space-y-1.5">
                              {o.template_missing ? (
                                <span className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-bold rounded-lg bg-rose-100 text-rose-800 border border-rose-300 select-none shadow-2xs">
                                  <Flag className="h-3 w-3" />
                                  <span>Chờ cập nhật</span>
                                </span>
                              ) : ['REVISION', 'REVISION_REQUESTED', 'FIX'].includes((o.state || '').toUpperCase()) ? (
                                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold rounded-lg bg-rose-100 text-rose-800 border border-rose-300 select-none shadow-2xs">
                                  <span className="h-2 w-2 rounded-full bg-rose-500 animate-pulse" />
                                  <span>Cần sửa gấp</span>
                                </span>
                              ) : ['QC_PENDING', 'RESULT_SUBMITTED', 'SUBMITTING_TO_SITE', 'REVIEW'].includes((o.state || '').toUpperCase()) ? (
                                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold rounded-lg bg-purple-100 text-purple-800 border border-purple-300 select-none shadow-2xs">
                                  <span className="h-2 w-2 rounded-full bg-purple-500" />
                                  <span>Chờ duyệt</span>
                                </span>
                              ) : ['DONE', 'CLAIMED_IMPORTED', 'COMPLETED', 'SKIPPED'].includes((o.state || '').toUpperCase()) ? (
                                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold rounded-lg bg-emerald-100 text-emerald-800 border border-emerald-300 select-none shadow-2xs">
                                  <span className="h-2 w-2 rounded-full bg-emerald-500" />
                                  <span>Hoàn thành</span>
                                </span>
                              ) : (
                                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-bold rounded-lg bg-blue-100 text-blue-800 border border-blue-300 select-none shadow-2xs">
                                  <span className="h-2 w-2 rounded-full bg-blue-500" />
                                  <span>{['WAITING', 'OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING', 'OPEN'].includes((o.state || '').toUpperCase()) ? 'Chờ chia' : 'Đang làm'}</span>
                                </span>
                              )}

                              {/* QC / Revision note */}
                              {['REVISION', 'REVISION_REQUESTED', 'FIX'].includes((o.state || '').toUpperCase()) && o.note_outsource && (
                                <div className="p-2 rounded-lg bg-amber-50 border border-amber-200 text-[11px] text-amber-950">
                                  <div className="font-bold flex items-center gap-1 text-amber-900 mb-0.5">
                                    <AlertTriangle className="h-3 w-3 text-amber-600 shrink-0" />
                                    <span>Ghi chú QC sửa lại:</span>
                                  </div>
                                  <div className="whitespace-pre-wrap break-all leading-tight text-slate-800 line-clamp-3">
                                    <LinkifiedText text={o.note_outsource} />
                                  </div>
                                </div>
                              )}

                              {/* Admin note */}
                              {o.admin_note && (
                                <div className="p-1.5 rounded-md bg-slate-50 border border-slate-200 text-[10px] text-slate-700">
                                  <span className="font-bold text-slate-800">Admin: </span>
                                  <span className="line-clamp-2">{o.admin_note}</span>
                                </div>
                              )}
                            </div>
                          </td>

                          {/* 4. Thời Gian */}
                          <td className="py-3 px-4 whitespace-nowrap">
                            {(() => {
                              const split = formatUtc7Split(o.status_changed_at)
                              if (!split) return <span className="text-slate-300 font-mono text-xs">-</span>
                              return (
                                <div className="flex flex-col leading-tight" title="Thời gian chuyển vào tab / cập nhật gần nhất (UTC+7)">
                                  <span className="font-mono text-xs font-bold text-slate-800">{split.time}</span>
                                  <span className="font-mono text-[11px] text-slate-500">{split.date}</span>
                                </div>
                              )
                            })()}
                          </td>

                          {/* 5. Nộp Link Bài Thiết Kế — chỉ hiển thị ở tab Đang làm */}
                          {activeDesignerTab === 'doing' && (
                            <td className="py-3 px-4" onClick={(e) => e.stopPropagation()}>
                              {(() => {
                                const stateUpper = (o.state || '').toUpperCase()
                                const isCompleted = ['DONE', 'CLAIMED_IMPORTED', 'COMPLETED', 'SKIPPED'].includes(stateUpper)
                                const isReview = ['QC_PENDING', 'RESULT_SUBMITTED', 'SUBMITTING_TO_SITE', 'REVIEW'].includes(stateUpper)
                                const isDoingOrFix = ['IN_PROGRESS', 'DOING', 'ASSIGNED', 'REVISION', 'REVISION_REQUESTED', 'FIX', 'OPEN', 'PENDING'].includes(stateUpper)
                                const currentLink = inlineSubmissionLinks[o.id] !== undefined ? inlineSubmissionLinks[o.id] : (o.drive_url || '')
                                const isSubmitting = Boolean(isSubmittingInline[o.id])

                                return (
                                  <div className="space-y-2">
                                    {/* Input & Submit for direct submission without entering details */}
                                    <div className="flex items-center gap-1.5">
                                      <input
                                        type="url"
                                        value={currentLink}
                                        onChange={(e) => setInlineSubmissionLinks((prev) => ({ ...prev, [o.id]: e.target.value }))}
                                        onKeyDown={(e) => {
                                          if (e.key === 'Enter' && !isSubmitting && !o.template_missing && currentLink.trim()) {
                                            e.preventDefault()
                                            handleInlineSubmit(o, currentLink)
                                          }
                                        }}
                                        placeholder="Dán link thiết kế (Drive, Canva, DropBox...)"
                                        disabled={isSubmitting || Boolean(o.template_missing)}
                                        className="flex-1 min-w-[200px] rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs text-slate-900 placeholder:text-slate-400 focus:border-[#0052CC] focus:ring-1 focus:ring-[#0052CC] shadow-2xs disabled:bg-slate-50 disabled:text-slate-400 disabled:cursor-not-allowed"
                                      />
                                      <OpenExternalLinkButton url={currentLink} label="Mở" />
                                      <button
                                        type="button"
                                        onClick={() => handleInlineSubmit(o, currentLink)}
                                        disabled={isSubmitting || Boolean(o.template_missing) || !currentLink.trim()}
                                        className="inline-flex items-center gap-1 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0043A6] disabled:bg-slate-300 disabled:cursor-not-allowed px-3 py-1.5 rounded-lg transition-colors cursor-pointer shadow-2xs shrink-0"
                                        title="Nộp bài và chuyển đơn sang Review chờ duyệt"
                                      >
                                        {isSubmitting ? (
                                          <>
                                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                            <span>Đang nộp…</span>
                                          </>
                                        ) : (
                                          <>
                                            <Send className="h-3.5 w-3.5" />
                                            <span>Nộp bài</span>
                                          </>
                                        )}
                                      </button>
                                    </div>

                                    {/* Action row underneath: Báo thiếu temp / link preview / review status */}
                                    <div className="flex items-center justify-between gap-2 pt-0.5">
                                      {!o.template_missing && isDoingOrFix && (
                                        <button
                                          type="button"
                                          onClick={() => flagMissingTemplate(o)}
                                          disabled={!o.assignment_id || flaggingMissingOrderId === o.id}
                                          className="inline-flex items-center gap-1 text-[11px] font-semibold text-rose-700 hover:text-rose-800 hover:bg-rose-50 px-2 py-0.5 rounded transition-colors disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
                                          title={!o.assignment_id ? 'Đơn chưa có assignment đang hoạt động' : 'Báo Admin rằng đơn này thiếu temp'}
                                        >
                                          {flaggingMissingOrderId === o.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Flag className="h-3 w-3" />}
                                          <span>{flaggingMissingOrderId === o.id ? 'Đang báo…' : 'Báo thiếu temp'}</span>
                                        </button>
                                      )}

                                      {o.template_missing && (
                                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-rose-700 bg-rose-50 px-2 py-0.5 rounded border border-rose-200">
                                          <Flag className="h-3 w-3 text-rose-600" />
                                          <span>Đang chờ Admin bổ sung temp</span>
                                        </span>
                                      )}

                                      {isReview && !o.template_missing && (
                                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-200">
                                          <Check className="h-3 w-3 text-purple-600" />
                                          <span>Đã nộp bài (Chờ duyệt)</span>
                                        </span>
                                      )}

                                      {isCompleted && (
                                        <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                                          <Check className="h-3 w-3 text-emerald-600 stroke-[3]" />
                                          <span>Đã hoàn thành</span>
                                        </span>
                                      )}

                                      {o.drive_url && (
                                        <a
                                          href={o.drive_url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="inline-flex items-center gap-1 text-[11px] font-bold text-[#0052CC] hover:underline ml-auto"
                                          title="Mở link bài thiết kế đã nộp"
                                        >
                                          <span>Xem link đã nộp</span>
                                          <ExternalLink className="h-2.5 w-2.5" />
                                        </a>
                                      )}
                                    </div>
                                  </div>
                                )
                              })()}
                            </td>
                          )}
                        </>
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
          onPageChange={handlePageChange}
        />
      </div>

      {/* Status-only Web mẹ update modal */}
      {platformStatusTarget && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
          onClick={() => !updatingPlatformStatus && setPlatformStatusTarget(null)}
        >
          <div
            className="relative w-full max-w-sm overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-slate-100 bg-slate-50 px-6 py-4">
              <div className="flex items-center gap-2">
                <RefreshCw className="h-5 w-5 text-[#0052CC]" />
                <h2 className="text-base font-bold text-slate-800">Cập nhật trạng thái Print</h2>
              </div>
              <button
                type="button"
                onClick={() => setPlatformStatusTarget(null)}
                disabled={updatingPlatformStatus}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-200 hover:text-slate-700 disabled:opacity-50"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <form onSubmit={handleUpdatePlatformStatus} className="space-y-4 p-6">
              <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs text-slate-700">
                <p className="font-bold text-slate-800">{platformStatusTarget.title}</p>
                {platformStatusTarget.currentStatus && (
                  <p className="mt-1">Trạng thái Web mẹ đã lưu: <strong>{platformStatusTarget.currentStatus}</strong></p>
                )}
              </div>
              <div className="space-y-1">
                <label className="block text-xs font-bold text-slate-700">Trạng thái mới trên Web mẹ</label>
                <select
                  value={platformStatusValue}
                  onChange={(e) => setPlatformStatusValue(e.target.value)}
                  className="w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs focus:border-[#0052CC] focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20"
                >
                  {PLATFORM_STATUS_OPTIONS.map((status) => (
                    <option key={status} value={status}>{status}</option>
                  ))}
                </select>
              </div>
              <p className="text-[11px] leading-relaxed text-slate-500">
                Thao tác này đẩy trạng thái lên Print. Hệ thống xếp việc vào worker nền và cập nhật kết quả tự động.
              </p>
              <div className="flex justify-end gap-2 border-t border-slate-100 pt-3">
                <button
                  type="button"
                  onClick={() => setPlatformStatusTarget(null)}
                  disabled={updatingPlatformStatus}
                  className="rounded-xl bg-slate-100 px-4 py-2 text-xs font-bold text-slate-600 hover:bg-slate-200 disabled:opacity-50"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={updatingPlatformStatus}
                  className="inline-flex items-center gap-1.5 rounded-xl bg-[#0052CC] px-4 py-2 text-xs font-bold text-white hover:bg-[#0041A3] disabled:opacity-50"
                >
                  {updatingPlatformStatus && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {updatingPlatformStatus ? 'Đang xếp hàng…' : `Cập nhật ${platformStatusTarget.orderIds.length} đơn`}
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
              <div className="text-xs space-y-1.5">
                <p className="text-slate-500 font-medium">
                  Đơn hàng: <strong className="text-slate-800 font-mono text-sm">{assigningOrder.external_order_id}</strong>
                </p>
                {assigningOrder.product_name && (
                  <p className="text-slate-600 line-clamp-1 font-semibold">{assigningOrder.product_name}</p>
                )}
                {assigningOrder.assigned_designer_name && (
                  <div className="flex items-center gap-1.5 text-[11px] text-blue-700 bg-blue-50 px-2.5 py-1 rounded-lg border border-blue-200">
                    <User className="h-3.5 w-3.5" />
                    <span>Hiện đang phân công: <strong>{assigningOrder.assigned_designer_name}</strong></span>
                  </div>
                )}
              </div>

              <div className="space-y-1">
                <label htmlFor="tacahu-designer-select" className="text-xs font-bold text-slate-700 block">
                  Chọn Designer Tacahu <span className="text-red-500">*</span>
                </label>
                <select
                  id="tacahu-designer-select"
                  required
                  value={selectedUserId}
                  onChange={(e) => setSelectedUserId(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
                >
                  <option value="">-- Chọn Designer --</option>
                  {regularDesigners.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name || u.username} ({u.role})
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Designer trên Web mẹ <span className="text-red-500">*</span>
                </label>
                <div className="flex items-center justify-between">
                  <button
                    type="button"
                    onClick={refreshPlatformDesignerOptions}
                    disabled={loadingPlatformOptions}
                    className="mb-1 text-[11px] font-semibold text-[#0052CC] hover:underline disabled:opacity-50"
                  >
                    Cập nhật danh sách từ Web mẹ
                  </button>
                </div>
                <select
                  required
                  value={selectedPlatformDesigner}
                  onChange={(e) => setSelectedPlatformDesigner(e.target.value)}
                  disabled={loadingPlatformOptions}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] disabled:bg-slate-100"
                >
                  <option value={DEFAULT_PLATFORM_DES}>{DEFAULT_PLATFORM_DES} (Mặc định)</option>
                  {platformDesigners.filter((d) => d !== DEFAULT_PLATFORM_DES).map((designer) => (
                    <option key={designer} value={designer}>{designer}</option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Trạng thái trên Web mẹ <span className="text-red-500">*</span>
                </label>
                <select
                  required
                  value={selectedPlatformStatus}
                  onChange={(e) => setSelectedPlatformStatus(e.target.value)}
                  disabled={loadingPlatformOptions}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] disabled:bg-slate-100"
                >
                  {(platformStatuses.length ? platformStatuses : ['Doing', 'Review', 'Fix', 'Done', 'Waiting']).map((status) => (
                    <option key={status} value={status}>{status}</option>
                  ))}
                </select>
              </div>

              <div className="pt-3 flex items-center justify-between gap-2 border-t border-slate-100">
                {assigningOrder.assigned_designer_name ? (
                  <button
                    type="button"
                    onClick={handleUnassignCurrentOrder}
                    disabled={assigning}
                    className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold text-red-600 hover:text-red-700 bg-red-50 hover:bg-red-100 border border-red-200 rounded-xl transition-colors cursor-pointer disabled:opacity-50"
                  >
                    <UserX className="h-3.5 w-3.5" />
                    <span>Hủy phân công</span>
                  </button>
                ) : (
                  <div />
                )}
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => setAssigningOrder(null)}
                    className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors cursor-pointer"
                  >
                    Hủy
                  </button>
                  <button
                    type="submit"
                    disabled={assigning || loadingPlatformOptions || !selectedUserId}
                    className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl transition-colors shadow-2xs disabled:opacity-50 cursor-pointer"
                  >
                    {assigning && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    <span>{assigning ? 'Đang phân công...' : 'Xác Nhận (Sang Doing)'}</span>
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      )}
      {/* Accept Fix Modal (Admin chấp nhận Fix & giao bài cho Des) */}
      {acceptFixOrder && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
          onClick={() => !acceptFixSubmitting && setAcceptFixOrder(null)}
        >
          <div
            className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col border border-slate-200"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-amber-50/80">
              <div className="flex items-center gap-2">
                <UserPlus className="h-5 w-5 text-amber-600" />
                <h2 className="text-base font-bold text-slate-800">Chấp Nhận Fix & Giao Cho Designer</h2>
              </div>
              <button
                onClick={() => !acceptFixSubmitting && setAcceptFixOrder(null)}
                disabled={acceptFixSubmitting}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors disabled:opacity-50"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleAcceptFix} className="p-6 space-y-4">
              <div className="text-xs space-y-1 bg-slate-50 p-3 rounded-xl border border-slate-200/70">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500 font-medium">Mã đơn hàng:</span>
                  <span className="font-mono font-bold text-[#0052CC] text-sm">{acceptFixOrder.external_order_id}</span>
                </div>
                {acceptFixOrder.product_name && (
                  <p className="text-slate-600 line-clamp-1 font-semibold mt-0.5">{acceptFixOrder.product_name}</p>
                )}
              </div>

              {/* Designer Selection */}
              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Designer tiếp quản <span className="text-red-500">*</span>
                </label>
                <select
                  value={acceptFixDesignerId}
                  onChange={(e) => setAcceptFixDesignerId(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] font-semibold text-slate-800"
                >
                  <option value="">-- Chọn Designer (Hoặc giữ nguyên) --</option>
                  {regularDesigners.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.full_name || u.username} {acceptFixOrder.assigned_designer_name === (u.full_name || u.username) ? '(Hiện tại)' : ''}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-slate-500">Mặc định giữ nguyên Designer đang phụ trách đơn.</p>
              </div>

              {/* Admin Note cho Designer */}
              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Ghi chú cho Designer (Note nội bộ)
                </label>
                <textarea
                  rows={2}
                  value={acceptFixDesignerNote}
                  onChange={(e) => setAcceptFixDesignerNote(e.target.value)}
                  placeholder="Nhập ghi chú / hướng dẫn cho Designer sửa bài..."
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] resize-none"
                />
              </div>

              {/* Outsource Note from Web mẹ */}
              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block flex items-center justify-between">
                  <span>Ghi chú Outsource (QC)</span>
                  <span className="text-[10px] text-amber-700 font-normal">Từ Print</span>
                </label>
                <textarea
                  rows={3}
                  value={acceptFixOutsourceNote}
                  onChange={(e) => setAcceptFixOutsourceNote(e.target.value)}
                  placeholder="Ghi chú lỗi từ phía Print..."
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-amber-50/40 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] resize-none font-mono"
                />
              </div>

              <div className="pt-3 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setAcceptFixOrder(null)}
                  disabled={acceptFixSubmitting}
                  className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors cursor-pointer disabled:opacity-50"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={acceptFixSubmitting}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-amber-600 hover:bg-amber-700 rounded-xl transition-colors shadow-2xs disabled:opacity-50 cursor-pointer"
                >
                  {acceptFixSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>{acceptFixSubmitting ? 'Đang lưu...' : 'Xác Nhận Giao Sửa'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Reject Fix Modal (Admin từ chối Fix & gửi lại Review trên Web mẹ) */}
      {rejectFixOrder && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
          onClick={() => !rejectFixSubmitting && setRejectFixOrder(null)}
        >
          <div
            className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col border border-slate-200"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-purple-50/80">
              <div className="flex items-center gap-2">
                <Undo2 className="h-5 w-5 text-purple-600" />
                <h2 className="text-base font-bold text-slate-800">Từ Chối Fix & Trả Lại Review</h2>
              </div>
              <button
                onClick={() => !rejectFixSubmitting && setRejectFixOrder(null)}
                disabled={rejectFixSubmitting}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors disabled:opacity-50"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleRejectFix} className="p-6 space-y-4">
              <div className="text-xs space-y-1 bg-slate-50 p-3 rounded-xl border border-slate-200/70">
                <div className="flex items-center justify-between">
                  <span className="text-slate-500 font-medium">Mã đơn hàng:</span>
                  <span className="font-mono font-bold text-[#0052CC] text-sm">{rejectFixOrder.external_order_id}</span>
                </div>
                {rejectFixOrder.assigned_designer_name && (
                  <p className="text-slate-600 font-semibold mt-0.5">
                    Designer: <span className="text-slate-800">{rejectFixOrder.assigned_designer_name}</span>
                  </p>
                )}
              </div>

              {/* Note Outsource field for explanation */}
              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Ghi chú Outsource gửi lên Print
                </label>
                <textarea
                  rows={4}
                  value={rejectFixOutsourceNote}
                  onChange={(e) => setRejectFixOutsourceNote(e.target.value)}
                  placeholder="Nhập giải trình lý do từ chối Fix hoặc ghi chú link hoàn thiện..."
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-purple-500/20 focus:border-purple-600 resize-none font-mono"
                />
              </div>

              <div className="rounded-xl border border-purple-100 bg-purple-50/60 p-3 text-[11px] leading-relaxed text-purple-900">
                <p className="font-bold mb-0.5 flex items-center gap-1">
                  <RefreshCw className="h-3.5 w-3.5 text-purple-600" />
                  <span>Cơ chế hoạt động:</span>
                </p>
                <span>
                  Hệ thống sẽ cập nhật trạng thái đơn trên Web mẹ thành <strong>Review</strong> kèm ghi chú outsource trên, và chuyển đơn trong hệ thống quay về tab <strong>Review</strong> để bên Print xem xét lại.
                </span>
              </div>

              <div className="pt-3 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setRejectFixOrder(null)}
                  disabled={rejectFixSubmitting}
                  className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors cursor-pointer disabled:opacity-50"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={rejectFixSubmitting}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-purple-600 hover:bg-purple-700 rounded-xl transition-colors shadow-2xs disabled:opacity-50 cursor-pointer"
                >
                  {rejectFixSubmitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>{rejectFixSubmitting ? 'Đang gửi...' : 'Xác Nhận Gửi Lại Review'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Bulk Delete Confirm Modal */}
      {deleteConfirmModalOpen && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
          onClick={() => !isBulkDeleting && setDeleteConfirmModalOpen(false)}
        >
          <div
            className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col border border-slate-200"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-rose-50/80">
              <div className="flex items-center gap-2">
                <Trash2 className="h-5 w-5 text-rose-600" />
                <h2 className="text-base font-bold text-slate-800">Xác Nhận Xóa Đơn Hàng Vĩnh Viễn</h2>
              </div>
              <button
                onClick={() => !isBulkDeleting && setDeleteConfirmModalOpen(false)}
                disabled={isBulkDeleting}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors disabled:opacity-50 cursor-pointer"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              <div className="p-3.5 bg-rose-50 border border-rose-200 rounded-xl text-xs text-rose-800 space-y-2">
                <p className="font-bold flex items-center gap-1.5 text-rose-900">
                  <AlertTriangle className="h-4 w-4 text-rose-600 shrink-0" />
                  <span>Cảnh báo hành động không thể hoàn tác!</span>
                </p>
                <p>
                  Bạn đang yêu cầu xóa vĩnh viễn <strong>{selectedOrderIds.length}</strong> đơn hàng khỏi hệ thống.
                  Toàn bộ thông tin phân công, bài nộp design, lịch sử timeline và ghi chú liên quan sẽ bị xóa sạch khỏi cơ sở dữ liệu.
                </p>
              </div>

              <div className="pt-3 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setDeleteConfirmModalOpen(false)}
                  disabled={isBulkDeleting}
                  className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors cursor-pointer disabled:opacity-50"
                >
                  Hủy bỏ
                </button>
                <button
                  type="button"
                  onClick={handleBulkDelete}
                  disabled={isBulkDeleting}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-rose-600 hover:bg-rose-700 rounded-xl transition-colors shadow-2xs disabled:opacity-50 cursor-pointer"
                >
                  {isBulkDeleting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>{isBulkDeleting ? 'Đang xóa...' : `Xác Nhận Xóa ${selectedOrderIds.length} Đơn`}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  )
}
