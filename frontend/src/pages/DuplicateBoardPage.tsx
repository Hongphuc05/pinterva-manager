import { useCallback, useEffect, useMemo, useState, type DragEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertCircle,
  ArrowDownUp,
  Check,
  CheckCircle2,
  Clock,
  Filter,
  GripHorizontal,
  GripVertical,
  Layers3,
  Package,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  User,
  UserRound,
  X,
} from 'lucide-react'
import { ApiError, apiFetch, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { AdminFixActionModal } from '../components/AdminFixActionModal'
import { CopyableOrderCode } from '../components/CopyableOrderCode'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { useToast } from '../context/ToastContext'

type DuplicateCard = {
  id: string
  external_order_id: string
  product_name: string | null
  thumbnail_url: string | null
  deadline_at_ext: string | null
  order_created_at_ext?: string | null
  created_at?: string | null
  status_changed_at?: string | null
  paid_at?: string | null
  is_paid?: boolean
  template_missing?: boolean
  state: string
  note_outsource: string
  previous_note_outsource: string | null
  fix_approved_by_admin: boolean
  assignee_id: string | null
  assignee_name: string | null
}

type ColumnMetrics = { total: number; doing: number; review: number; fix: number; done: number }

type DuplicateColumn = {
  id: string
  title: string
  column_type?: string
  metrics: ColumnMetrics
  cards: DuplicateCard[]
}

type FixAction = {
  orderId: string
  externalOrderId: string
  mode: 'approve' | 'reject'
  currentNote: string
  previousNote: string | null
}

function stateLabel(state: string) {
  const labels: Record<string, string> = {
    OPEN: 'Chờ xử lý',
    WAITING: 'Waiting',
    IN_PROGRESS: 'Doing',
    QC_PENDING: 'Review',
    REVISION: 'Fix',
    DONE: 'Done',
    CANCELLED: 'Đã hủy',
  }
  return labels[state] || state
}

function stateClass(state: string) {
  if (state === 'DONE') return 'bg-emerald-50 text-emerald-700 border-emerald-200'
  if (state === 'REVISION') return 'bg-orange-50 text-orange-700 border-orange-200'
  if (state === 'QC_PENDING') return 'bg-violet-50 text-violet-700 border-violet-200'
  if (state === 'IN_PROGRESS') return 'bg-blue-50 text-blue-700 border-blue-200'
  return 'bg-slate-100 text-slate-600 border-slate-200'
}

const stateSortRank: Record<string, number> = {
  OPEN: 0,
  WAITING: 0,
  IN_PROGRESS: 1,
  QC_PENDING: 2,
  REVISION: 3,
  DONE: 4,
  CANCELLED: 5,
}

function sortedCards(cards: DuplicateCard[], statusSortEnabled: boolean) {
  if (!statusSortEnabled) return cards
  return [...cards].sort((left, right) => {
    const stateDifference = (stateSortRank[left.state] ?? 99) - (stateSortRank[right.state] ?? 99)
    if (stateDifference !== 0) return stateDifference
    return (left.deadline_at_ext || '').localeCompare(right.deadline_at_ext || '')
  })
}

export function DuplicateBoardPage() {
  const { user } = useAuth()
  const { showToast } = useToast()
  const { status: syncStatus, triggerRun, isTriggering } = useSyncStatus()
  const [columns, setColumns] = useState<DuplicateColumn[]>([])
  const [crossDesignerDragEnabled, setCrossDesignerDragEnabled] = useState(true)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [draggedCard, setDraggedCard] = useState<DuplicateCard | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const [movingCardId, setMovingCardId] = useState<string | null>(null)
  const [statusSortColumns, setStatusSortColumns] = useState<Set<string>>(() => new Set())
  const [savingSettings, setSavingSettings] = useState(false)
  const [syncRequested, setSyncRequested] = useState(false)
  const [fixAction, setFixAction] = useState<FixAction | null>(null)

  // Global board search and filters
  const [searchQuery, setSearchQuery] = useState('')
  const [globalStateFilter, setGlobalStateFilter] = useState<'all' | 'doing' | 'review' | 'fix' | 'done' | 'missing'>('all')
  const [globalDesignerFilter, setGlobalDesignerFilter] = useState<string>('all')

  // Done column filters
  const [doneDesignerFilter, setDoneDesignerFilter] = useState<string>('all')
  const [donePaymentFilter, setDonePaymentFilter] = useState<'all' | 'unpaid' | 'paid'>('all')
  const [doneTimeFilter, setDoneTimeFilter] = useState<'all' | 'today' | '7days' | '30days'>('all')

  // Custom column order (stored in localStorage)
  const [customColumnOrder, setCustomColumnOrder] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem('duplicate_board_column_order') || '[]')
    } catch {
      return []
    }
  })
  const [draggedColumnId, setDraggedColumnId] = useState<string | null>(null)
  const [columnDropTarget, setColumnDropTarget] = useState<string | null>(null)

  const isAdmin = user?.role === 'admin'
  const isSupport = user?.role === 'support'

  const loadBoard = useCallback(async () => {
    setLoading(true)
    try {
      const result = await apiFetch<{ columns: DuplicateColumn[]; cross_designer_drag_enabled: boolean }>('/duplicate-board')
      setColumns(result.columns)
      setCrossDesignerDragEnabled(result.cross_designer_drag_enabled)
      setError(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể tải board Đơn trùng lặp.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadBoard()
  }, [loadBoard])

  useEffect(() => {
    const handleOrdersUpdated = () => { void loadBoard() }
    window.addEventListener('orders-updated', handleOrdersUpdated)
    return () => window.removeEventListener('orders-updated', handleOrdersUpdated)
  }, [loadBoard])

  const boardOrderIds = useMemo(() => columns.flatMap((column) => column.cards.map((card) => card.id)), [columns])

  const syncBoardStatus = useCallback(async () => {
    if (boardOrderIds.length === 0) {
      setError('Board chưa có đơn để đồng bộ trạng thái.')
      return
    }
    setError(null)
    setSyncRequested(true)
    try {
      await triggerRun(boardOrderIds)
    } catch (caught) {
      setSyncRequested(false)
      setError(caught instanceof ApiError ? caught.message : 'Không thể gửi tác vụ đồng bộ.')
      window.dispatchEvent(new CustomEvent('sync-printerval-end'))
    }
  }, [boardOrderIds, triggerRun])

  useEffect(() => {
    const handleSyncCurrentTab = () => {
      window.dispatchEvent(new CustomEvent('sync-tab-handled'))
      void syncBoardStatus()
    }
    window.addEventListener('request-sync-current-tab', handleSyncCurrentTab)
    return () => window.removeEventListener('request-sync-current-tab', handleSyncCurrentTab)
  }, [syncBoardStatus])

  useEffect(() => {
    if (!syncRequested || isTriggering || syncStatus?.is_running) return
    setSyncRequested(false)
    void loadBoard()
    window.dispatchEvent(new CustomEvent('sync-printerval-end'))
  }, [isTriggering, loadBoard, syncRequested, syncStatus?.is_running])

  // Get all unique designers that exist across the board
  const allDesignersList = useMemo(() => {
    const map = new Map<string, string>()
    columns.forEach((col) => {
      if (col.id !== 'orders' && col.id !== 'missing_form' && col.id !== 'unassigned' && col.id !== 'done') {
        map.set(col.id, col.title)
      }
      col.cards.forEach((card) => {
        if (card.assignee_id && card.assignee_name) {
          map.set(card.assignee_id, card.assignee_name)
        }
      })
    })
    return Array.from(map.entries()).map(([id, name]) => ({ id, name }))
  }, [columns])

  // Aggregate KPI stats across the whole board
  const boardKPIs = useMemo(() => {
    let total = 0
    let doing = 0
    let review = 0
    let fix = 0
    let done = 0
    let missing = 0

    columns.forEach((col) => {
      col.cards.forEach((card) => {
        total++
        if (card.template_missing) missing++
        if (card.state === 'IN_PROGRESS') doing++
        else if (card.state === 'QC_PENDING') review++
        else if (card.state === 'REVISION') fix++
        else if (card.state === 'DONE') done++
      })
    })

    return { total, doing, review, fix, done, missing }
  }, [columns])

  // Filter Done column cards (supports Designer, Payment, Time filters)
  const filterDoneCards = useCallback((cards: DuplicateCard[]) => {
    return cards.filter((card) => {
      // 1. Designer filter
      if (doneDesignerFilter !== 'all') {
        if (card.assignee_id !== doneDesignerFilter && card.assignee_name !== doneDesignerFilter) {
          return false
        }
      }
      // 2. Payment status filter
      if (donePaymentFilter === 'paid' && !card.is_paid) return false
      if (donePaymentFilter === 'unpaid' && card.is_paid) return false

      // 3. Time filter
      if (doneTimeFilter !== 'all') {
        const timeStr = card.status_changed_at || card.paid_at || card.created_at
        if (!timeStr) return false
        const cardDate = new Date(timeStr).getTime()
        const now = Date.now()
        if (doneTimeFilter === 'today') {
          const startOfToday = new Date()
          startOfToday.setHours(0, 0, 0, 0)
          if (cardDate < startOfToday.getTime()) return false
        } else if (doneTimeFilter === '7days') {
          if (now - cardDate > 7 * 24 * 3600 * 1000) return false
        } else if (doneTimeFilter === '30days') {
          if (now - cardDate > 30 * 24 * 3600 * 1000) return false
        }
      }
      return true
    })
  }, [doneDesignerFilter, donePaymentFilter, doneTimeFilter])

  // Global card filter applied across columns
  const filterCardGlobal = useCallback((card: DuplicateCard) => {
    // 1. Search Query filter (order code, product name, assignee)
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase()
      const matchCode = card.external_order_id.toLowerCase().includes(q)
      const matchProduct = card.product_name ? card.product_name.toLowerCase().includes(q) : false
      const matchAssignee = card.assignee_name ? card.assignee_name.toLowerCase().includes(q) : false
      if (!matchCode && !matchProduct && !matchAssignee) {
        return false
      }
    }

    // 2. Global State filter
    if (globalStateFilter !== 'all') {
      if (globalStateFilter === 'doing' && card.state !== 'IN_PROGRESS') return false
      if (globalStateFilter === 'review' && card.state !== 'QC_PENDING') return false
      if (globalStateFilter === 'fix' && card.state !== 'REVISION') return false
      if (globalStateFilter === 'done' && card.state !== 'DONE') return false
      if (globalStateFilter === 'missing' && !card.template_missing) return false
    }

    // 3. Global Designer filter
    if (globalDesignerFilter !== 'all') {
      if (card.assignee_id !== globalDesignerFilter && card.assignee_name !== globalDesignerFilter) {
        return false
      }
    }

    return true
  }, [searchQuery, globalStateFilter, globalDesignerFilter])

  // Reorder columns according to custom order (or default)
  const orderedColumns = useMemo(() => {
    if (columns.length === 0) return []

    // If no custom order saved, maintain default: [orders, missing_form, ...designers, done]
    if (!customColumnOrder || customColumnOrder.length === 0) {
      return columns
    }

    const colMap = new Map(columns.map((c) => [c.id, c]))
    const ordered: DuplicateColumn[] = []

    // Add columns in custom order if they still exist
    customColumnOrder.forEach((id) => {
      const col = colMap.get(id)
      if (col) {
        ordered.push(col)
        colMap.delete(id)
      }
    })

    // Any new columns (e.g. newly added Trello designers) insert before 'done'
    const doneCol = colMap.get('done')
    colMap.delete('done')

    colMap.forEach((col) => {
      ordered.push(col)
    })

    if (doneCol && !ordered.some((c) => c.id === 'done')) {
      ordered.push(doneCol)
    }

    return ordered
  }, [columns, customColumnOrder])

  function handleColumnDragStart(event: DragEvent<HTMLDivElement>, columnId: string) {
    setDraggedColumnId(columnId)
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/column-id', columnId)
  }

  function handleColumnDrop(event: DragEvent<HTMLElement>, targetColumnId: string) {
    if (!draggedColumnId || draggedColumnId === targetColumnId) {
      setDraggedColumnId(null)
      setColumnDropTarget(null)
      return
    }
    event.preventDefault()
    event.stopPropagation()

    const currentOrder = orderedColumns.map((c) => c.id)
    const fromIdx = currentOrder.indexOf(draggedColumnId)
    const toIdx = currentOrder.indexOf(targetColumnId)

    if (fromIdx !== -1 && toIdx !== -1) {
      const newOrder = [...currentOrder]
      const [removed] = newOrder.splice(fromIdx, 1)
      newOrder.splice(toIdx, 0, removed)
      setCustomColumnOrder(newOrder)
      try {
        localStorage.setItem('duplicate_board_column_order', JSON.stringify(newOrder))
      } catch (e) {
        console.error('Failed to save column order:', e)
      }
    }
    setDraggedColumnId(null)
    setColumnDropTarget(null)
  }

  function canDropTo(column: DuplicateColumn) {
    if (!draggedCard || movingCardId || isSupport) return false
    if (isAdmin) return true

    // Designer Trello rules:
    const myId = user?.id
    // Can always drop into own column
    if (column.id === myId) return true

    // If dragging a card currently assigned to this designer:
    if (draggedCard.assignee_id === myId) {
      // Can drop to done, missing_form, orders, or other designer if cross drag enabled
      if (column.id === 'done' || column.id === 'missing_form' || column.id === 'orders' || column.id === 'unassigned') {
        return true
      }
      return crossDesignerDragEnabled
    }

    // If dragging an unassigned card (from orders or missing_form): can claim to own column
    if (!draggedCard.assignee_id && column.id === myId) {
      return true
    }

    return crossDesignerDragEnabled
  }

  function onDragStart(event: DragEvent<HTMLDivElement>, card: DuplicateCard) {
    setDraggedCard(card)
    event.dataTransfer.effectAllowed = 'move'
    event.dataTransfer.setData('text/plain', card.id)
  }

  function onDragEnd() {
    setDraggedCard(null)
    setDropTarget(null)
  }

  async function onDrop(event: DragEvent<HTMLElement>, column: DuplicateColumn) {
    event.preventDefault()
    if (!draggedCard || !canDropTo(column)) return

    // Determine target identifiers
    const isOrders = column.id === 'orders'
    const isMissing = column.id === 'missing_form' || column.id === 'unassigned'
    const isDone = column.id === 'done'
    const isDesigner = !isOrders && !isMissing && !isDone

    // Avoid redundant move to the same state
    if (isOrders && !draggedCard.assignee_id && !draggedCard.template_missing && draggedCard.state !== 'DONE') {
      onDragEnd()
      return
    }
    if (isMissing && !draggedCard.assignee_id && draggedCard.template_missing) {
      onDragEnd()
      return
    }
    if (isDone && draggedCard.state === 'DONE') {
      onDragEnd()
      return
    }
    if (isDesigner && draggedCard.assignee_id === column.id && draggedCard.state !== 'DONE') {
      onDragEnd()
      return
    }

    setMovingCardId(draggedCard.id)
    const movedOrderCode = draggedCard.external_order_id
    try {
      await apiFetch('/duplicate-board/move', {
        method: 'POST',
        body: JSON.stringify({
          order_id: draggedCard.id,
          target_column_id: column.id,
          target_designer_id: isDesigner ? column.id : null,
        }),
      })
      await loadBoard()
      if (isDesigner) {
        showToast(`Đã phân công đơn ${movedOrderCode} cho ${column.title} và chuyển sang Doing.`, 'success')
      } else if (isDone) {
        showToast(`Đã chuyển đơn ${movedOrderCode} sang Done.`, 'success')
      } else if (isMissing) {
        showToast(`Đã chuyển đơn ${movedOrderCode} sang Thiếu form.`, 'warning')
      } else if (isOrders) {
        showToast(`Đã chuyển đơn ${movedOrderCode} về kho Đơn hàng.`, 'info')
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể di chuyển thẻ.')
    } finally {
      setMovingCardId(null)
      onDragEnd()
    }
  }

  async function updateCrossDesignerDrag(enabled: boolean) {
    if (!isAdmin) return
    setSavingSettings(true)
    try {
      const result = await apiFetch<{ cross_designer_drag_enabled: boolean }>('/duplicate-board/settings', {
        method: 'PUT',
        body: JSON.stringify({ cross_designer_drag_enabled: enabled }),
      })
      setCrossDesignerDragEnabled(result.cross_designer_drag_enabled)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể lưu quyền kéo thẻ.')
    } finally {
      setSavingSettings(false)
    }
  }

  function toggleStatusSort(columnId: string) {
    setStatusSortColumns((current) => {
      const next = new Set(current)
      if (next.has(columnId)) next.delete(columnId)
      else next.add(columnId)
      return next
    })
  }

  const hasActiveFilters = searchQuery.trim() !== '' || globalStateFilter !== 'all' || globalDesignerFilter !== 'all'

  function resetAllFilters() {
    setSearchQuery('')
    setGlobalStateFilter('all')
    setGlobalDesignerFilter('all')
    setDoneDesignerFilter('all')
    setDonePaymentFilter('all')
    setDoneTimeFilter('all')
  }

  return (
    <DashboardLayout>
      <section className="-m-6 min-h-[calc(100vh-4rem)] bg-[#f1f2f4] p-6 lg:-m-8 lg:p-8">
        {/* Main Board Header */}
        <header className="mb-4 flex flex-col gap-4 rounded-2xl border border-slate-200 bg-white px-5 py-4 shadow-xs">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="flex items-center gap-2 text-lg font-bold text-slate-800">
                <Layers3 className="h-5 w-5 text-violet-600" />
                Board Đơn trùng lặp
              </h1>
              <p className="mt-1 text-xs text-slate-500">
                Không gian làm việc kéo thả dành cho Đơn trùng lặp — đồng bộ trực quan cho Admin và Designer Trello.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  window.dispatchEvent(new CustomEvent('sync-printerval-start'))
                  void syncBoardStatus()
                }}
                disabled={syncRequested || isTriggering || syncStatus?.is_running || boardOrderIds.length === 0}
                className="inline-flex items-center justify-center gap-2 rounded-lg bg-[#0052CC] px-3.5 py-2 text-xs font-bold text-white shadow-xs hover:bg-[#0041A3] disabled:opacity-50 cursor-pointer"
                title="Đồng bộ trạng thái từ Printerval cho tất cả đơn trên board"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${(syncRequested || isTriggering || syncStatus?.is_running) ? 'animate-spin' : ''}`} />
                <span>{(syncRequested || isTriggering || syncStatus?.is_running) ? 'Đang đồng bộ...' : 'Đồng bộ trạng thái'}</span>
              </button>

              {isAdmin ? (
                <label className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 cursor-pointer select-none hover:bg-slate-50">
                  <Settings2 className="h-3.5 w-3.5 text-slate-500" />
                  <input
                    type="checkbox"
                    checked={crossDesignerDragEnabled}
                    disabled={savingSettings}
                    onChange={(event) => { void updateCrossDesignerDrag(event.target.checked) }}
                    className="h-3.5 w-3.5 accent-[#0052CC]"
                  />
                  <span>Des kéo chéo</span>
                </label>
              ) : (
                <div className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-2 text-xs font-medium text-slate-600">
                  <span className={`h-2 w-2 rounded-full ${crossDesignerDragEnabled ? 'bg-emerald-500' : 'bg-slate-400'}`}></span>
                  <span>{crossDesignerDragEnabled ? 'Kéo tự do' : 'Kéo theo phân quyền'}</span>
                </div>
              )}

              <button
                type="button"
                onClick={() => { void loadBoard() }}
                disabled={loading || movingCardId !== null}
                className="inline-flex items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-bold text-slate-700 shadow-xs hover:bg-slate-50 disabled:opacity-50 cursor-pointer"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
                <span>Làm mới board</span>
              </button>
            </div>
          </div>

          {/* KPI Summary Strip */}
          <div className="grid grid-cols-2 gap-2 pt-2 border-t border-slate-100 sm:grid-cols-3 md:grid-cols-6 text-xs">
            <div className="rounded-xl border border-slate-200 bg-slate-50/70 p-2.5 text-center">
              <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">Tổng Đơn</div>
              <div className="mt-0.5 text-lg font-black font-mono text-slate-800">{boardKPIs.total}</div>
            </div>
            <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-2.5 text-center">
              <div className="text-[10px] font-bold uppercase tracking-wider text-blue-700">Đang Làm</div>
              <div className="mt-0.5 text-lg font-black font-mono text-blue-800">{boardKPIs.doing}</div>
            </div>
            <div className="rounded-xl border border-violet-200 bg-violet-50/60 p-2.5 text-center">
              <div className="text-[10px] font-bold uppercase tracking-wider text-violet-700">Chờ Duyệt</div>
              <div className="mt-0.5 text-lg font-black font-mono text-violet-800">{boardKPIs.review}</div>
            </div>
            <div className="rounded-xl border border-orange-200 bg-orange-50/60 p-2.5 text-center">
              <div className="text-[10px] font-bold uppercase tracking-wider text-orange-700">Cần Sửa (Fix)</div>
              <div className="mt-0.5 text-lg font-black font-mono text-orange-800">{boardKPIs.fix}</div>
            </div>
            <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-2.5 text-center">
              <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-700">Done</div>
              <div className="mt-0.5 text-lg font-black font-mono text-emerald-800">{boardKPIs.done}</div>
            </div>
            <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-2.5 text-center">
              <div className="text-[10px] font-bold uppercase tracking-wider text-amber-700">Thiếu Form</div>
              <div className="mt-0.5 text-lg font-black font-mono text-amber-800">{boardKPIs.missing}</div>
            </div>
          </div>

          {/* Global Search & Filters Bar */}
          <div className="flex flex-col gap-2 pt-2 border-t border-slate-100 md:flex-row md:items-center md:justify-between">
            <div className="flex flex-1 flex-wrap items-center gap-2">
              {/* Search input */}
              <div className="relative min-w-[220px] flex-1 max-w-sm">
                <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Tìm mã đơn, tên sản phẩm..."
                  className="w-full rounded-lg border border-slate-200 bg-slate-50 py-1.5 pl-8 pr-7 text-xs text-slate-800 placeholder-slate-400 focus:border-[#0052CC] focus:bg-white focus:outline-none focus:ring-1 focus:ring-[#0052CC]"
                />
                {searchQuery && (
                  <button
                    type="button"
                    onClick={() => setSearchQuery('')}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              {/* Status Filter */}
              <select
                value={globalStateFilter}
                onChange={(e) => setGlobalStateFilter(e.target.value as any)}
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 focus:border-[#0052CC] focus:outline-none focus:ring-1 focus:ring-[#0052CC]"
              >
                <option value="all">Tất cả trạng thái</option>
                <option value="doing">Đang làm (Doing)</option>
                <option value="review">Chờ duyệt (Review)</option>
                <option value="fix">Cần sửa (Fix)</option>
                <option value="done">Hoàn thành (Done)</option>
                <option value="missing">Thiếu form</option>
              </select>

              {/* Designer Filter */}
              <select
                value={globalDesignerFilter}
                onChange={(e) => setGlobalDesignerFilter(e.target.value)}
                className="rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 focus:border-[#0052CC] focus:outline-none focus:ring-1 focus:ring-[#0052CC]"
              >
                <option value="all">Tất cả Designer ({allDesignersList.length})</option>
                {allDesignersList.map((des) => (
                  <option key={des.id} value={des.id}>
                    DES: {des.name}
                  </option>
                ))}
              </select>

              {hasActiveFilters && (
                <button
                  type="button"
                  onClick={resetAllFilters}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs font-bold text-slate-600 hover:bg-slate-50 cursor-pointer"
                  title="Xóa bộ lọc"
                >
                  <RotateCcw className="h-3 w-3" />
                  <span>Xóa lọc</span>
                </button>
              )}
            </div>

            <div className="text-[11px] text-slate-400 font-medium self-end md:self-center">
              Kéo thả tiêu đề cột để sắp xếp lại vị trí hiển thị
            </div>
          </div>
        </header>

        {error && (
          <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-xs font-semibold text-red-700">
            <span className="flex items-center gap-2"><AlertCircle className="h-4 w-4" />{error}</span>
            <button type="button" onClick={() => setError(null)} className="font-bold cursor-pointer">Đóng</button>
          </div>
        )}

        {loading && columns.length === 0 ? (
          <div className="flex gap-4 overflow-hidden">
            {[1, 2, 3, 4].map((item) => <div key={item} className="h-96 w-80 shrink-0 animate-pulse rounded-xl bg-slate-200" />)}
          </div>
        ) : (
          <div className="flex min-h-[calc(100vh-15rem)] gap-4 overflow-x-auto pb-5">
            {orderedColumns.map((column) => {
              const isDoneCol = column.id === 'done'
              const canDrop = canDropTo(column)
              const rawCards = column.cards

              // First apply Done column specific filters if this is the Done column
              const stage1Cards = isDoneCol ? filterDoneCards(rawCards) : rawCards
              // Then apply global board filters (search query, state, designer)
              const displayedCards = stage1Cards.filter(filterCardGlobal)
              const cards = sortedCards(displayedCards, statusSortColumns.has(column.id))

              return (
                <section
                  key={column.id}
                  onDragOver={(event) => {
                    if (draggedCard && canDrop) {
                      event.preventDefault()
                      event.dataTransfer.dropEffect = 'move'
                      setDropTarget(column.id)
                    } else if (draggedColumnId && draggedColumnId !== column.id) {
                      event.preventDefault()
                      setColumnDropTarget(column.id)
                    }
                  }}
                  onDragLeave={() => {
                    setDropTarget((current) => current === column.id ? null : current)
                    setColumnDropTarget((current) => current === column.id ? null : current)
                  }}
                  onDrop={(event) => {
                    if (draggedCard) {
                      void onDrop(event, column)
                    } else if (draggedColumnId) {
                      handleColumnDrop(event, column.id)
                    }
                  }}
                  className={`flex w-80 shrink-0 flex-col rounded-xl border p-3 transition-all ${
                    columnDropTarget === column.id
                      ? 'border-indigo-500 bg-indigo-50/70 ring-2 ring-indigo-400'
                      : dropTarget === column.id && canDrop
                      ? 'border-violet-400 bg-violet-100 ring-2 ring-violet-300/60'
                      : isDoneCol
                      ? 'border-emerald-200 bg-emerald-50/40'
                      : column.id === 'orders'
                      ? 'border-blue-200 bg-blue-50/40'
                      : column.id === 'missing_form' || column.id === 'unassigned'
                      ? 'border-amber-200 bg-amber-50/40'
                      : 'border-slate-200 bg-slate-200/80'
                  }`}
                >
                  {/* Column Header (Draggable for both Admin & Des) */}
                  <div
                    draggable={true}
                    onDragStart={(e) => handleColumnDragStart(e, column.id)}
                    className="mb-3 space-y-2 px-1 cursor-grab active:cursor-grabbing select-none"
                    title="Kéo thả tiêu đề cột để thay đổi thứ tự"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <GripHorizontal className="h-3.5 w-3.5 text-slate-400 shrink-0 hover:text-slate-600" />
                        <h2 className="truncate text-sm font-bold text-slate-800">
                          {column.title}
                        </h2>
                      </div>
                      <div className="flex items-center gap-1.5 shrink-0">
                        {!isDoneCol && (
                          <button
                            type="button"
                            onClick={() => toggleStatusSort(column.id)}
                            title="Sắp xếp Doing, Review, Fix, Done"
                            className={`rounded p-1 transition-colors cursor-pointer ${
                              statusSortColumns.has(column.id)
                                ? 'bg-violet-100 text-violet-700'
                                : 'text-slate-500 hover:bg-white hover:text-slate-700'
                            }`}
                          >
                            <ArrowDownUp className="h-3.5 w-3.5" />
                          </button>
                        )}
                        <span className="rounded-full bg-white px-2 py-0.5 font-mono text-[11px] font-bold text-slate-600 shadow-xs border border-slate-200">
                          {displayedCards.length < rawCards.length ? `${displayedCards.length}/${rawCards.length}` : column.metrics.total}
                        </span>
                      </div>
                    </div>

                    {/* Metrics row (for non-done columns) */}
                    {!isDoneCol && (
                      <div className="flex flex-wrap gap-1 text-[10px] font-semibold">
                        <span className="rounded bg-blue-50 px-1.5 py-0.5 text-blue-700 border border-blue-100">Doing {column.metrics.doing}</span>
                        <span className="rounded bg-violet-50 px-1.5 py-0.5 text-violet-700 border border-violet-100">Review {column.metrics.review}</span>
                        <span className="rounded bg-orange-50 px-1.5 py-0.5 text-orange-700 border border-orange-100">Fix {column.metrics.fix}</span>
                        <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-emerald-700 border border-emerald-100">Done {column.metrics.done}</span>
                      </div>
                    )}

                    {/* Filter bar (specifically for Done column) */}
                    {isDoneCol && (
                      <div className="space-y-1.5 pt-1 border-t border-emerald-200/60 text-xs">
                        <div className="flex items-center gap-1 text-[10px] font-bold text-emerald-900 uppercase tracking-wider">
                          <Filter className="h-3 w-3 text-emerald-700" />
                          <span>Bộ lọc Done</span>
                        </div>

                        {/* 1. Designer filter */}
                        <select
                          value={doneDesignerFilter}
                          onChange={(e) => setDoneDesignerFilter(e.target.value)}
                          className="w-full text-[11px] font-semibold bg-white border border-emerald-300 rounded-lg px-2 py-1 text-slate-700 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                        >
                          <option value="all">Tất cả Designer ({allDesignersList.length})</option>
                          {allDesignersList.map((des) => (
                            <option key={des.id} value={des.id}>
                              DES: {des.name}
                            </option>
                          ))}
                        </select>

                        <div className="grid grid-cols-2 gap-1.5">
                          {/* 2. Payment filter */}
                          <select
                            value={donePaymentFilter}
                            onChange={(e) => setDonePaymentFilter(e.target.value as any)}
                            className="text-[10px] font-semibold bg-white border border-emerald-300 rounded-lg px-1.5 py-1 text-slate-700 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                          >
                            <option value="all">Tất cả thanh toán</option>
                            <option value="unpaid">Chưa thanh toán</option>
                            <option value="paid">Đã thanh toán</option>
                          </select>

                          {/* 3. Time filter */}
                          <select
                            value={doneTimeFilter}
                            onChange={(e) => setDoneTimeFilter(e.target.value as any)}
                            className="text-[10px] font-semibold bg-white border border-emerald-300 rounded-lg px-1.5 py-1 text-slate-700 focus:outline-none focus:ring-1 focus:ring-emerald-500"
                          >
                            <option value="all">Tất cả thời gian</option>
                            <option value="today">Hôm nay</option>
                            <option value="7days">7 ngày qua</option>
                            <option value="30days">30 ngày qua</option>
                          </select>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Cards container */}
                  <div className="min-h-28 space-y-2">
                    {cards.map((card) => (
                      <div
                        key={card.id}
                        draggable={!movingCardId && !isSupport}
                        onDragStart={(event) => onDragStart(event, card)}
                        onDragEnd={onDragEnd}
                        className={`group rounded-lg border border-slate-200 bg-white p-3 shadow-2xs transition-all hover:shadow-md ${
                          draggedCard?.id === card.id ? 'opacity-40 scale-95' : ''
                        } ${movingCardId === card.id ? 'pointer-events-none opacity-60' : isSupport ? 'cursor-default' : 'cursor-grab active:cursor-grabbing'}`}
                      >
                        <div className="flex gap-2.5">
                          <GripVertical className="mt-0.5 h-4 w-3 shrink-0 text-slate-300 group-hover:text-slate-500" />
                          {card.thumbnail_url ? (
                            <img src={resolveAssetUrl(card.thumbnail_url)} alt="" className="h-11 w-11 rounded-md border border-slate-200 object-cover shrink-0" />
                          ) : (
                            <div className="flex h-11 w-11 items-center justify-center rounded-md border border-slate-200 bg-slate-50 text-slate-400 shrink-0">
                              <Package className="h-5 w-5" />
                            </div>
                          )}
                          <div className="min-w-0 flex-1">
                            <CopyableOrderCode code={card.external_order_id} />
                            <Link to={`/orders/${card.id}`} className="block hover:underline">
                              <p className="mt-0.5 line-clamp-2 text-[11px] font-medium leading-relaxed text-slate-600">
                                {card.product_name || 'Đơn chưa có tên sản phẩm'}
                              </p>
                            </Link>
                          </div>
                        </div>

                        {/* Extra card details in Done column */}
                        {isDoneCol && (
                          <div className="mt-2.5 flex flex-wrap items-center gap-1.5 text-[10px]">
                            {card.assignee_name && (
                              <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-blue-50 text-[#0052CC] font-semibold border border-blue-100">
                                <User className="h-3 w-3" />
                                <span>{card.assignee_name}</span>
                              </span>
                            )}
                            <span className={`inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded font-bold border ${
                              card.is_paid
                                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                : 'bg-slate-100 text-slate-600 border-slate-200'
                            }`}>
                              {card.is_paid ? <CheckCircle2 className="h-3 w-3 text-emerald-600" /> : <Clock className="h-3 w-3 text-slate-400" />}
                              <span>{card.is_paid ? 'Đã thanh toán' : 'Chưa thanh toán'}</span>
                            </span>
                          </div>
                        )}

                        <div className="mt-2.5 flex items-center justify-between gap-2 border-t border-slate-100 pt-2 text-[10px]">
                          <span className={`rounded border px-1.5 py-0.5 font-bold ${stateClass(card.state)}`}>
                            {stateLabel(card.state)}
                          </span>
                          {card.deadline_at_ext && (
                            <span className="font-medium text-slate-400">
                              {new Date(card.deadline_at_ext).toLocaleDateString('vi-VN')}
                            </span>
                          )}
                        </div>

                        {isAdmin && card.state === 'REVISION' && !card.fix_approved_by_admin && (
                          <div className="mt-2 flex gap-1.5 border-t border-orange-100 pt-2">
                            <button
                              type="button"
                              draggable={false}
                              onClick={() => setFixAction({
                                orderId: card.id,
                                externalOrderId: card.external_order_id,
                                mode: 'approve',
                                currentNote: card.note_outsource,
                                previousNote: card.previous_note_outsource,
                              })}
                              className="flex-1 inline-flex items-center justify-center gap-1 rounded-md bg-emerald-600 px-1.5 py-1 text-[10px] font-bold text-white hover:bg-emerald-700 cursor-pointer"
                            >
                              <Check className="h-3 w-3" /> Check & Duyệt
                            </button>
                            <button
                              type="button"
                              draggable={false}
                              onClick={() => setFixAction({
                                orderId: card.id,
                                externalOrderId: card.external_order_id,
                                mode: 'reject',
                                currentNote: card.note_outsource,
                                previousNote: card.previous_note_outsource,
                              })}
                              className="inline-flex items-center justify-center gap-1 rounded-md border border-slate-300 bg-white px-1.5 py-1 text-[10px] font-bold text-slate-700 hover:bg-slate-50 cursor-pointer"
                            >
                              <RotateCcw className="h-3 w-3" /> Trả Review
                            </button>
                          </div>
                        )}
                      </div>
                    ))}

                    {cards.length === 0 && (
                      <div className={`rounded-lg border border-dashed p-5 text-center text-xs ${
                        dropTarget === column.id ? 'border-violet-400 text-violet-700' : 'border-slate-300 text-slate-400'
                      }`}>
                        <UserRound className="mx-auto mb-1 h-4 w-4 opacity-60" />
                        {column.id === 'orders'
                          ? 'Chưa có đơn trùng lặp mới'
                          : column.id === 'missing_form' || column.id === 'unassigned'
                          ? 'Chưa có đơn thiếu form'
                          : column.id === 'done'
                          ? 'Chưa có đơn hoàn thành'
                          : 'Kéo đơn vào đây'}
                      </div>
                    )}
                  </div>
                </section>
              )
            })}
          </div>
        )}
      </section>

      {fixAction && (
        <AdminFixActionModal
          isOpen
          mode={fixAction.mode}
          orderId={fixAction.orderId}
          externalOrderId={fixAction.externalOrderId}
          currentNote={fixAction.currentNote}
          previousNote={fixAction.previousNote}
          onClose={() => setFixAction(null)}
          onSuccess={() => { void loadBoard() }}
        />
      )}
    </DashboardLayout>
  )
}
