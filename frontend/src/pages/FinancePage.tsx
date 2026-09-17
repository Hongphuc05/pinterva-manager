import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch, ApiError, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useToast } from '../context/ToastContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { Pagination } from '../components/Pagination'
import { ImageModal } from '../components/ImageModal'
import { CopyableOrderCode } from '../components/CopyableOrderCode'
import { OrderHistoryTimelineModal } from '../components/OrderHistoryTimelineModal'
import { getStatusInfo, resolveExternalUrl } from '../utils/statusTranslation'
import {
  Coins,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Users,
  Search,
  Filter,
  RotateCcw,
  ExternalLink,
  ChevronRight,
  Package,
  Loader2,
  FileText,
  MessageSquare,
  Plus,
  Trash2,
  Edit2,
  Calendar,
  X,
  History,
  Check,
  Download,
  CreditCard
} from 'lucide-react'

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

export type DesignerSummary = {
  designer_id: string | null
  designer_name: string
  username: string | null
  total_tasks: number
  unpaid_tasks: number
  paid_tasks: number
  in_review_tasks: number
  in_fix_tasks: number
  done_tasks: number
  first_submission_at: string | null
  latest_submission_at: string | null
  notes_count?: number
}

export type CreditedTask = {
  order_id: string
  external_order_id: string
  product_name: string | null
  thumbnail_url: string | null
  designer_id: string | null
  designer_name: string
  current_state: string
  printerval_status: string | null
  drive_link: string | null
  placeholder_filled?: boolean
  status_changed_at: string | null
  review_submitted_at?: string | null
  first_submitted_at: string
  latest_submitted_at: string
  submission_count: number
  order_created_at: string
  notes_count?: number
  is_paid?: boolean
  paid_at?: string | null
  paid_by_id?: string | null
}

export type FinanceStatsResponse = {
  total_credited_tasks: number
  total_unpaid_tasks: number
  total_paid_tasks: number
  total_designers: number
  total_done_tasks: number
  total_in_review_tasks: number
  total_in_fix_tasks: number
  designers_summary: DesignerSummary[]
  tasks: CreditedTask[]
  total_tasks_count: number
  page: number
  page_size: number
  total_pages: number
}

export type FinanceNote = {
  id: string
  target_type: 'order' | 'designer'
  order_id: string | null
  order_code: string | null
  designer_id: string | null
  designer_name: string | null
  author_id: string | null
  author_name: string
  content: string
  created_at: string
  updated_at: string
}

export type FinanceNoteListResponse = {
  notes: FinanceNote[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

export function FinancePage() {
  const { user } = useAuth()
  const { showToast } = useToast()
  const isAdmin = user?.role === 'admin'

  // Top sub-tabs: 'finance' (Stats & Payment Management) vs 'notes' (Admin Notes)
  const [activeMainTab, setActiveMainTab] = useState<'finance' | 'notes'>('finance')

  // Payment status sub-tabs: 'unpaid' (Chưa thanh toán) vs 'paid' (Đã thanh toán)
  const [paymentSubTab, setPaymentSubTab] = useState<'unpaid' | 'paid'>('unpaid')

  // Data states
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<FinanceStatsResponse | null>(null)

  // Filters
  const [selectedDesigner, setSelectedDesigner] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState('')
  const [stateFilter, setStateFilter] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [datePreset, setDatePreset] = useState<string>('')
  const [currentPage, setCurrentPage] = useState(1)

  // Selection & Shift + Click
  const [selectedOrderIds, setSelectedOrderIds] = useState<string[]>([])
  const [lastSelectedOrderIndex, setLastSelectedOrderIndex] = useState<number | null>(null)
  const [processingAction, setProcessingAction] = useState(false)

  // Export Excel Modal
  const [exportModalOpen, setExportModalOpen] = useState(false)
  const [exportStartDate, setExportStartDate] = useState('')
  const [exportEndDate, setExportEndDate] = useState('')
  const [exportDesignerId, setExportDesignerId] = useState('ALL')
  const [exportPaymentStatus, setExportPaymentStatus] = useState<'all' | 'unpaid' | 'paid'>('all')
  const [exporting, setExporting] = useState(false)

  // Timeline Modal
  const [timelineOrder, setTimelineOrder] = useState<{ id: string; code: string; name?: string | null } | null>(null)

  // Image zoom modal
  const [selectedImage, setSelectedImage] = useState<string | null>(null)

  // Notes state
  const [notesData, setNotesData] = useState<FinanceNoteListResponse | null>(null)
  const [notesLoading, setNotesLoading] = useState(false)
  const [notesSearch, setNotesSearch] = useState('')
  const [notesTargetFilter, setNotesTargetFilter] = useState<'all' | 'order' | 'designer'>('all')
  const [notesDesignerFilter, setNotesDesignerFilter] = useState('')
  const [notesPage, setNotesPage] = useState(1)

  // Add/Edit Note Modal
  const [noteModalOpen, setNoteModalOpen] = useState(false)
  const [editingNote, setEditingNote] = useState<FinanceNote | null>(null)
  const [noteTargetType, setNoteTargetType] = useState<'order' | 'designer'>('order')
  const [noteOrderId, setNoteOrderId] = useState('')
  const [noteOrderCode, setNoteOrderCode] = useState('')
  const [noteDesignerId, setNoteDesignerId] = useState('')
  const [noteDesignerName, setNoteDesignerName] = useState('')
  const [noteContent, setNoteContent] = useState('')
  const [noteSaving, setNoteSaving] = useState(false)

  // Modal for Designer detail tasks (Admin)
  const [selectedDesignerForModal, setSelectedDesignerForModal] = useState<DesignerSummary | null>(null)
  const [modalPaymentTab, setModalPaymentTab] = useState<'unpaid' | 'paid'>('unpaid')
  const [modalTasks, setModalTasks] = useState<CreditedTask[]>([])
  const [modalTasksLoading, setModalTasksLoading] = useState(false)
  const [modalTotalCount, setModalTotalCount] = useState(0)
  const [modalPage, setModalPage] = useState(1)
  const [modalSearchQuery, setModalSearchQuery] = useState('')
  const [modalStateFilter, setModalStateFilter] = useState('')
  const [modalSelectedOrderIds, setModalSelectedOrderIds] = useState<string[]>([])
  const [modalLastSelectedIndex, setModalLastSelectedIndex] = useState<number | null>(null)
  const [orderRates, setOrderRates] = useState<Record<string, number>>({})

  // Quick date presets
  function applyDatePreset(preset: 'today' | 'yesterday' | '7days' | 'this_month' | 'all') {
    setDatePreset(preset)
    const now = new Date()
    const toDateStr = (d: Date) => {
      const year = d.getFullYear()
      const month = String(d.getMonth() + 1).padStart(2, '0')
      const day = String(d.getDate()).padStart(2, '0')
      return `${year}-${month}-${day}`
    }

    if (preset === 'today') {
      const todayStr = toDateStr(now)
      setStartDate(todayStr)
      setEndDate(todayStr)
    } else if (preset === 'yesterday') {
      const y = new Date(now)
      y.setDate(y.getDate() - 1)
      const yStr = toDateStr(y)
      setStartDate(yStr)
      setEndDate(yStr)
    } else if (preset === '7days') {
      const past = new Date(now)
      past.setDate(past.getDate() - 6)
      setStartDate(toDateStr(past))
      setEndDate(toDateStr(now))
    } else if (preset === 'this_month') {
      const firstDay = new Date(now.getFullYear(), now.getMonth(), 1)
      setStartDate(toDateStr(firstDay))
      setEndDate(toDateStr(now))
    } else if (preset === 'all') {
      setStartDate('')
      setEndDate('')
    }
    setCurrentPage(1)
  }

  // Load Finance Stats
  async function loadData() {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', currentPage.toString())
      params.set('page_size', '50')
      params.set('is_paid', paymentSubTab === 'paid' ? 'true' : 'false')
      if (selectedDesigner) params.set('designer_id', selectedDesigner)
      if (searchQuery.trim()) params.set('search', searchQuery.trim())
      if (stateFilter) params.set('state', stateFilter)
      if (startDate) params.set('start_date', startDate)
      if (endDate) params.set('end_date', endDate)

      const res = await apiFetch<FinanceStatsResponse>(`/finance/stats?${params.toString()}`)
      setData(res)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không tải được dữ liệu tài chính.')
    } finally {
      setLoading(false)
    }
  }

  // Load Notes
  async function loadNotes() {
    setNotesLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', notesPage.toString())
      params.set('page_size', '50')
      if (notesTargetFilter !== 'all') params.set('target_type', notesTargetFilter)
      if (notesDesignerFilter) params.set('designer_id', notesDesignerFilter)
      if (notesSearch.trim()) params.set('search', notesSearch.trim())

      const res = await apiFetch<FinanceNoteListResponse>(`/finance/notes?${params.toString()}`)
      setNotesData(res)
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không tải được danh sách ghi chú.', 'error')
    } finally {
      setNotesLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage, selectedDesigner, stateFilter, startDate, endDate, paymentSubTab])

  useEffect(() => {
    if (activeMainTab === 'notes') {
      loadNotes()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeMainTab, notesPage, notesTargetFilter, notesDesignerFilter])

  // Search debounce for stats
  useEffect(() => {
    const timer = setTimeout(() => {
      setCurrentPage(1)
      loadData()
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery])

  // Search debounce for notes
  useEffect(() => {
    const timer = setTimeout(() => {
      setNotesPage(1)
      if (activeMainTab === 'notes') loadNotes()
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [notesSearch])

  // Shift + Click Range Selection
  function handleSelectOrder(orderId: string, index: number, event?: React.MouseEvent) {
    if (event?.shiftKey && lastSelectedOrderIndex !== null && data?.tasks) {
      const start = Math.min(lastSelectedOrderIndex, index)
      const end = Math.max(lastSelectedOrderIndex, index)
      const rangeIds = data.tasks.slice(start, end + 1).map((t) => t.order_id)
      setSelectedOrderIds((prev) => Array.from(new Set([...prev, ...rangeIds])))
    } else {
      setSelectedOrderIds((prev) =>
        prev.includes(orderId) ? prev.filter((id) => id !== orderId) : [...prev, orderId]
      )
      setLastSelectedOrderIndex(index)
    }
  }

  function handleSelectAll() {
    if (!data?.tasks || data.tasks.length === 0) return
    const currentTaskIds = data.tasks.map((t) => t.order_id)
    const isAllSelected = currentTaskIds.every((id) => selectedOrderIds.includes(id))
    if (isAllSelected) {
      setSelectedOrderIds((prev) => prev.filter((id) => !currentTaskIds.includes(id)))
    } else {
      setSelectedOrderIds((prev) => Array.from(new Set([...prev, ...currentTaskIds])))
    }
  }

  // Mark Orders as Paid (Admin)
  async function handleMarkPaid(orderIdsToMark?: string[]) {
    const ids = orderIdsToMark || selectedOrderIds
    if (!ids.length) return
    setProcessingAction(true)
    try {
      const res = await apiFetch<{ ok: boolean; updated_count: number }>('/finance/mark-paid', {
        method: 'POST',
        body: JSON.stringify({ order_ids: ids }),
      })
      showToast(`Đã xác nhận thanh toán cho ${res.updated_count} đơn hàng!`, 'success')
      setSelectedOrderIds([])
      setLastSelectedOrderIndex(null)
      loadData()
    } catch (err: any) {
      showToast(err.message || 'Không thể xác nhận thanh toán.', 'error')
    } finally {
      setProcessingAction(false)
    }
  }

  // Unmark Orders as Paid (Admin)
  async function handleUnmarkPaid(orderIdsToUnmark?: string[]) {
    const ids = orderIdsToUnmark || selectedOrderIds
    if (!ids.length) return
    if (!window.confirm(`Bạn có chắc chắn muốn hủy trạng thái thanh toán của ${ids.length} đơn hàng này không?`)) {
      return
    }
    setProcessingAction(true)
    try {
      const res = await apiFetch<{ ok: boolean; updated_count: number }>('/finance/unmark-paid', {
        method: 'POST',
        body: JSON.stringify({ order_ids: ids }),
      })
      showToast(`Đã hủy thanh toán cho ${res.updated_count} đơn hàng!`, 'success')
      setSelectedOrderIds([])
      setLastSelectedOrderIndex(null)
      loadData()
    } catch (err: any) {
      showToast(err.message || 'Không thể hủy thanh toán.', 'error')
    } finally {
      setProcessingAction(false)
    }
  }

  // --- Modal Specific Data Loading & Actions (Admin) ---
  async function loadModalTasks() {
    if (!selectedDesignerForModal) return
    setModalTasksLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', modalPage.toString())
      params.set('page_size', '50')
      params.set('is_paid', modalPaymentTab === 'paid' ? 'true' : 'false')
      params.set('designer_id', selectedDesignerForModal.designer_id || selectedDesignerForModal.designer_name)
      if (modalSearchQuery.trim()) params.set('search', modalSearchQuery.trim())
      if (modalStateFilter) params.set('state', modalStateFilter)

      const res = await apiFetch<FinanceStatsResponse>(`/finance/stats?${params.toString()}`)
      setModalTasks(res.tasks || [])
      setModalTotalCount(res.total_tasks_count || 0)
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không tải được danh sách đơn của Designer.', 'error')
    } finally {
      setModalTasksLoading(false)
    }
  }

  useEffect(() => {
    if (selectedDesignerForModal) {
      loadModalTasks()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDesignerForModal, modalPaymentTab, modalPage, modalStateFilter])

  useEffect(() => {
    if (!selectedDesignerForModal) return
    const timer = setTimeout(() => {
      setModalPage(1)
      loadModalTasks()
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [modalSearchQuery])

  function handleRateChange(orderId: string, delta: number) {
    setOrderRates((prev) => {
      const current = prev[orderId] ?? 40000
      const next = Math.max(0, current + delta)
      return { ...prev, [orderId]: next }
    })
  }

  function handleModalSelectOrder(orderId: string, index: number, event?: React.MouseEvent) {
    if (event?.shiftKey && modalLastSelectedIndex !== null && modalTasks.length > 0) {
      const start = Math.min(modalLastSelectedIndex, index)
      const end = Math.max(modalLastSelectedIndex, index)
      const rangeIds = modalTasks.slice(start, end + 1).map((t) => t.order_id)
      setModalSelectedOrderIds((prev) => Array.from(new Set([...prev, ...rangeIds])))
    } else {
      setModalSelectedOrderIds((prev) =>
        prev.includes(orderId) ? prev.filter((id) => id !== orderId) : [...prev, orderId]
      )
      setModalLastSelectedIndex(index)
    }
  }

  function handleModalSelectAll() {
    if (!modalTasks || modalTasks.length === 0) return
    const currentTaskIds = modalTasks.map((t) => t.order_id)
    const isAllSelected = currentTaskIds.every((id) => modalSelectedOrderIds.includes(id))
    if (isAllSelected) {
      setModalSelectedOrderIds((prev) => prev.filter((id) => !currentTaskIds.includes(id)))
    } else {
      setModalSelectedOrderIds((prev) => Array.from(new Set([...prev, ...currentTaskIds])))
    }
  }

  async function handleModalMarkPaid(orderIdsToMark?: string[]) {
    const ids = orderIdsToMark && orderIdsToMark.length > 0
      ? orderIdsToMark
      : (modalSelectedOrderIds.length > 0 ? modalSelectedOrderIds : modalTasks.map((t) => t.order_id))
    if (!ids.length) {
      showToast('Không có đơn hàng nào để thanh toán.', 'warning')
      return
    }
    if (ids.length > 1 && !window.confirm(`Xác nhận thanh toán cho ${ids.length} đơn hàng của Designer này?`)) {
      return
    }
    setProcessingAction(true)
    try {
      const res = await apiFetch<{ ok: boolean; updated_count: number }>('/finance/mark-paid', {
        method: 'POST',
        body: JSON.stringify({ order_ids: ids }),
      })
      showToast(`Đã xác nhận thanh toán cho ${res.updated_count} đơn hàng!`, 'success')
      setModalSelectedOrderIds([])
      setModalLastSelectedIndex(null)
      loadModalTasks()
      loadData()
    } catch (err: any) {
      showToast(err.message || 'Không thể xác nhận thanh toán.', 'error')
    } finally {
      setProcessingAction(false)
    }
  }

  async function handleModalUnmarkPaid(orderIdsToUnmark?: string[]) {
    const ids = orderIdsToUnmark && orderIdsToUnmark.length > 0
      ? orderIdsToUnmark
      : (modalSelectedOrderIds.length > 0 ? modalSelectedOrderIds : modalTasks.map((t) => t.order_id))
    if (!ids.length) {
      showToast('Không có đơn hàng nào để hủy thanh toán.', 'warning')
      return
    }
    if (!window.confirm(`Bạn có chắc chắn muốn hủy trạng thái thanh toán của ${ids.length} đơn hàng này không?`)) {
      return
    }
    setProcessingAction(true)
    try {
      const res = await apiFetch<{ ok: boolean; updated_count: number }>('/finance/unmark-paid', {
        method: 'POST',
        body: JSON.stringify({ order_ids: ids }),
      })
      showToast(`Đã hủy thanh toán cho ${res.updated_count} đơn hàng!`, 'success')
      setModalSelectedOrderIds([])
      setModalLastSelectedIndex(null)
      loadModalTasks()
      loadData()
    } catch (err: any) {
      showToast(err.message || 'Không thể hủy thanh toán.', 'error')
    } finally {
      setProcessingAction(false)
    }
  }

  // Export Excel / CSV Download
  async function handleDownloadExcel() {
    setExporting(true)
    try {
      const params = new URLSearchParams()
      if (exportStartDate) params.set('start_date', exportStartDate)
      if (exportEndDate) params.set('end_date', exportEndDate)
      if (exportDesignerId && exportDesignerId !== 'ALL') params.set('designer_id', exportDesignerId)
      if (exportPaymentStatus !== 'all') params.set('is_paid', exportPaymentStatus === 'paid' ? 'true' : 'false')

      const token = localStorage.getItem('token')
      const activePlatformId = localStorage.getItem('activePlatformId')
      const baseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
      const headers: Record<string, string> = {}
      if (token) headers['Authorization'] = `Bearer ${token}`
      if (activePlatformId) headers['X-Platform-Id'] = activePlatformId

      const resp = await fetch(`${baseUrl}/api/finance/export-excel?${params.toString()}`, {
        headers,
      })
      if (!resp.ok) throw new Error('Không thể tải file Excel.')
      const blob = await resp.blob()
      const downloadUrl = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = downloadUrl
      a.download = `bao_cao_tai_chinh_${new Date().toISOString().slice(0, 10)}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(downloadUrl)
      setExportModalOpen(false)
      showToast('Đã xuất file Excel thành công!', 'success')
    } catch (err: any) {
      showToast(err.message || 'Lỗi khi xuất file Excel', 'error')
    } finally {
      setExporting(false)
    }
  }

  // Open note modal
  function openAddNoteModal(type: 'order' | 'designer', targetId?: string, targetLabel?: string) {
    setEditingNote(null)
    setNoteTargetType(type)
    if (type === 'order') {
      setNoteOrderId(targetId || '')
      setNoteOrderCode(targetLabel || '')
      setNoteDesignerId('')
      setNoteDesignerName('')
    } else {
      setNoteDesignerId(targetId || '')
      setNoteDesignerName(targetLabel || '')
      setNoteOrderId('')
      setNoteOrderCode('')
    }
    setNoteContent('')
    setNoteModalOpen(true)
  }

  function openEditNoteModal(note: FinanceNote) {
    setEditingNote(note)
    setNoteTargetType(note.target_type)
    setNoteOrderId(note.order_id || '')
    setNoteOrderCode(note.order_code || '')
    setNoteDesignerId(note.designer_id || '')
    setNoteDesignerName(note.designer_name || '')
    setNoteContent(note.content)
    setNoteModalOpen(true)
  }

  async function handleSaveNote() {
    if (!noteContent.trim()) {
      showToast('Vui lòng nhập nội dung ghi chú', 'warning')
      return
    }
    setNoteSaving(true)
    try {
      if (editingNote) {
        await apiFetch(`/finance/notes/${editingNote.id}`, {
          method: 'PUT',
          body: JSON.stringify({ content: noteContent.trim() }),
        })
        showToast('Đã cập nhật ghi chú thành công!', 'success')
      } else {
        await apiFetch('/finance/notes', {
          method: 'POST',
          body: JSON.stringify({
            target_type: noteTargetType,
            order_id: noteOrderId || null,
            order_code: noteOrderCode || null,
            designer_id: noteDesignerId || null,
            designer_name: noteDesignerName || null,
            content: noteContent.trim(),
          }),
        })
        showToast('Đã thêm ghi chú thành công!', 'success')
      }
      setNoteModalOpen(false)
      loadData()
      if (activeMainTab === 'notes') loadNotes()
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể lưu ghi chú.', 'error')
    } finally {
      setNoteSaving(false)
    }
  }

  async function handleDeleteNote(noteId: string) {
    if (!window.confirm('Bạn có chắc chắn muốn xóa ghi chú này không?')) return
    try {
      await apiFetch(`/finance/notes/${noteId}`, { method: 'DELETE' })
      showToast('Đã xóa ghi chú thành công!', 'success')
      loadNotes()
      loadData()
    } catch (err) {
      showToast(err instanceof ApiError ? err.message : 'Không thể xóa ghi chú.', 'error')
    }
  }

  const allCurrentIdsSelected =
    (data?.tasks?.length ?? 0) > 0 &&
    data?.tasks?.every((t) => selectedOrderIds.includes(t.order_id))

  return (
    <DashboardLayout>
      {/* Image Zoom Modal */}
      <ImageModal
        isOpen={!!selectedImage}
        onClose={() => setSelectedImage(null)}
        imageUrl={selectedImage}
      />

      {/* Order Timeline History Modal */}
      {timelineOrder && (
        <OrderHistoryTimelineModal
          isOpen={!!timelineOrder}
          onClose={() => setTimelineOrder(null)}
          orderId={timelineOrder.id}
          externalOrderId={timelineOrder.code}
          productName={timelineOrder.name}
        />
      )}

      {/* Header Banner */}
      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-xs flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3.5">
          <div className="w-12 h-12 rounded-xl bg-blue-50 border border-blue-100 flex items-center justify-center text-[#0052CC] flex-shrink-0">
            <Coins className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-gray-900 flex items-center gap-2">
              {isAdmin ? 'Quản Lý Tài Chính & Công Lao Designer' : 'Tài Chính Của Tôi'}
            </h1>
            <p className="text-xs text-gray-500 mt-0.5">
              {isAdmin
                ? 'Theo dõi công lao nộp bài, xác nhận thanh toán cho từng Designer và xuất file Excel báo cáo đối soát.'
                : 'Theo dõi chi tiết tất cả các đơn bạn đã nộp bài, tiến độ ghi nhận công và trạng thái thanh toán từ Admin.'}
            </p>
          </div>
        </div>

        {/* Top Actions: Export Excel & Sub-Tabs */}
        <div className="flex items-center gap-2.5 flex-wrap">
          {isAdmin && (
            <>
              <button
                type="button"
                onClick={() => setExportModalOpen(true)}
                className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-bold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 border border-emerald-200 rounded-xl transition-all cursor-pointer shadow-2xs"
              >
                <Download className="h-4 w-4 text-emerald-600" />
                <span>Xuất Excel</span>
              </button>

              <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl border border-slate-200">
                <button
                  type="button"
                  onClick={() => setActiveMainTab('finance')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    activeMainTab === 'finance'
                      ? 'bg-white text-[#0052CC] shadow-xs'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <Coins className="h-3.5 w-3.5" />
                  <span>Tính Công & Thanh Toán</span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveMainTab('notes')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                    activeMainTab === 'notes'
                      ? 'bg-white text-[#0052CC] shadow-xs'
                      : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  <MessageSquare className="h-3.5 w-3.5" />
                  <span>Ghi Chú Admin (Notes)</span>
                  {notesData?.total ? (
                    <span className="bg-blue-100 text-[#0052CC] px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold">
                      {notesData.total}
                    </span>
                  ) : null}
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-xs font-medium flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-red-600 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 1: FINANCE & PAYMENT MANAGEMENT                                       */}
      {/* ========================================================================= */}
      {activeMainTab === 'finance' && (
        <div className="space-y-6">
          {/* Global Summary KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Tổng Đơn Tính Công</p>
                <h3 className="text-2xl font-bold font-mono text-[#0052CC] mt-1">
                  {data?.total_credited_tasks ?? 0}
                </h3>
                <p className="text-[11px] text-slate-400 mt-0.5">Vào Review + Có link bài</p>
              </div>
              <div className="p-3 bg-blue-50 text-[#0052CC] rounded-xl border border-blue-100">
                <CheckCircle2 className="h-6 w-6" />
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Chưa Thanh Toán</p>
                <h3 className="text-2xl font-bold font-mono text-amber-600 mt-1">
                  {data?.total_unpaid_tasks ?? 0}
                </h3>
                <p className="text-[11px] text-slate-400 mt-0.5">Chờ thanh toán công</p>
              </div>
              <div className="p-3 bg-amber-50 text-amber-600 rounded-xl border border-amber-100">
                <Clock className="h-6 w-6" />
              </div>
            </div>

            <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Đã Thanh Toán</p>
                <h3 className="text-2xl font-bold font-mono text-emerald-600 mt-1">
                  {data?.total_paid_tasks ?? 0}
                </h3>
                <p className="text-[11px] text-slate-400 mt-0.5">Admin đã xác nhận</p>
              </div>
              <div className="p-3 bg-emerald-50 text-emerald-600 rounded-xl border border-emerald-100">
                <CreditCard className="h-6 w-6" />
              </div>
            </div>

            {isAdmin ? (
              <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Designer Hoạt Động</p>
                  <h3 className="text-2xl font-bold font-mono text-purple-600 mt-1">
                    {data?.total_designers ?? 0}
                  </h3>
                  <p className="text-[11px] text-slate-400 mt-0.5">Có đơn nộp bài</p>
                </div>
                <div className="p-3 bg-purple-50 text-purple-600 rounded-xl border border-purple-100">
                  <Users className="h-6 w-6" />
                </div>
              </div>
            ) : (
              <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs flex items-center justify-between">
                <div>
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Đã Hoàn Thành (Done)</p>
                  <h3 className="text-2xl font-bold font-mono text-emerald-600 mt-1">
                    {data?.total_done_tasks ?? 0}
                  </h3>
                  <p className="text-[11px] text-slate-400 mt-0.5">Đơn duyệt hoàn tất</p>
                </div>
                <div className="p-3 bg-emerald-50 text-emerald-600 rounded-xl border border-emerald-100">
                  <CheckCircle2 className="h-6 w-6" />
                </div>
              </div>
            )}
          </div>

          {/* Admin Designer Summary Table */}
          {isAdmin && data?.designers_summary && data.designers_summary.length > 0 && (
            <div className="rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden">
              <div className="px-5 py-3.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between flex-wrap gap-2">
                <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-2">
                  <Users className="h-4 w-4 text-[#0052CC]" />
                  <span>Bảng Tổng Hợp Công & Thanh Toán Theo Designer ({data.designers_summary.length})</span>
                </h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-slate-50/50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500">
                      <th className="py-3 px-4">Designer</th>
                      <th className="py-3 px-4 text-center">Chưa Thanh Toán</th>
                      <th className="py-3 px-4 text-center">Đã Thanh Toán</th>
                      <th className="py-3 px-4 text-center">Tổng Công</th>
                      <th className="py-3 px-4 text-center">Chờ Review</th>
                      <th className="py-3 px-4 text-center">Cần Fix</th>
                      <th className="py-3 px-4 text-center">Đã Xong</th>
                      <th className="py-3 px-4 whitespace-nowrap">Lần Nộp Đầu</th>
                      <th className="py-3 px-4 whitespace-nowrap">Lần Nộp Gần Nhất</th>
                      <th className="py-3 px-4 text-center">Ghi Chú</th>
                      <th className="py-3 px-4 text-right">Thao Tác</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {data.designers_summary.map((des) => {
                      const firstSplit = formatUtc7Split(des.first_submission_at)
                      const latestSplit = formatUtc7Split(des.latest_submission_at)

                      return (
                        <tr
                          key={des.designer_name}
                          className="transition-colors hover:bg-blue-50/40"
                        >
                          <td className="py-3 px-4 font-semibold text-slate-800">
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedDesignerForModal(des)
                                setModalPaymentTab(des.unpaid_tasks > 0 ? 'unpaid' : (des.paid_tasks > 0 ? 'paid' : 'unpaid'))
                                setModalPage(1)
                                setModalSelectedOrderIds([])
                                setModalSearchQuery('')
                                setModalStateFilter('')
                              }}
                              className="flex items-center gap-2 text-left hover:text-[#0052CC] cursor-pointer"
                            >
                              <div className="w-7 h-7 rounded-full bg-blue-100 text-[#0052CC] font-bold flex items-center justify-center text-xs">
                                {des.designer_name.charAt(0).toUpperCase()}
                              </div>
                              <div>
                                <p className="font-semibold text-slate-800">{des.designer_name}</p>
                                {des.username && <p className="text-[10px] text-slate-400 font-normal">@{des.username}</p>}
                              </div>
                            </button>
                          </td>
                          <td className="py-3 px-4 text-center">
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-bold bg-amber-50 text-amber-700 border border-amber-200">
                              {des.unpaid_tasks ?? 0} đơn
                            </span>
                          </td>
                          <td className="py-3 px-4 text-center">
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                              {des.paid_tasks ?? 0} đơn
                            </span>
                          </td>
                          <td className="py-3 px-4 text-center">
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-bold bg-blue-50 text-[#0052CC] border border-blue-200">
                              {des.total_tasks} công
                            </span>
                          </td>
                          <td className="py-3 px-4 text-center">
                            <span className="font-mono font-semibold text-purple-700">
                              {des.in_review_tasks}
                            </span>
                          </td>
                          <td className="py-3 px-4 text-center">
                            <span className="font-mono font-semibold text-orange-700">
                              {des.in_fix_tasks}
                            </span>
                          </td>
                          <td className="py-3 px-4 text-center">
                            <span className="font-mono font-semibold text-emerald-700">
                              {des.done_tasks}
                            </span>
                          </td>
                          <td className="py-3 px-4 whitespace-nowrap">
                            {firstSplit ? (
                              <div className="flex flex-col leading-tight">
                                <span className="font-mono text-xs font-semibold text-slate-700">{firstSplit.time}</span>
                                <span className="font-mono text-[10px] text-slate-400">{firstSplit.date}</span>
                              </div>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>
                          <td className="py-3 px-4 whitespace-nowrap">
                            {latestSplit ? (
                              <div className="flex flex-col leading-tight">
                                <span className="font-mono text-xs font-semibold text-slate-700">{latestSplit.time}</span>
                                <span className="font-mono text-[10px] text-slate-400">{latestSplit.date}</span>
                              </div>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-center">
                            {des.notes_count && des.notes_count > 0 ? (
                              <button
                                type="button"
                                onClick={() => {
                                  setNotesTargetFilter('designer')
                                  setNotesDesignerFilter(des.designer_id || des.designer_name)
                                  setActiveMainTab('notes')
                                }}
                                className="inline-flex items-center gap-1 text-[11px] font-bold text-amber-800 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full hover:bg-amber-100 transition-colors cursor-pointer"
                              >
                                <MessageSquare className="h-3 w-3 text-amber-600" />
                                <span>{des.notes_count} note</span>
                              </button>
                            ) : (
                              <span className="text-slate-300 text-[11px]">-</span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <div className="flex items-center justify-end gap-1.5">
                              <button
                                type="button"
                                onClick={() => openAddNoteModal('designer', des.designer_id || undefined, des.designer_name)}
                                className="inline-flex items-center gap-1 px-2 py-1 text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-amber-50 hover:text-amber-800 hover:border-amber-200 rounded-lg border border-slate-200 transition-all cursor-pointer"
                                title="Thêm ghi chú cho Designer này"
                              >
                                <Plus className="h-3 w-3" />
                                <span>Note</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => {
                                  setSelectedDesignerForModal(des)
                                  setModalPaymentTab(des.unpaid_tasks > 0 ? 'unpaid' : (des.paid_tasks > 0 ? 'paid' : 'unpaid'))
                                  setModalPage(1)
                                  setModalSelectedOrderIds([])
                                  setModalSearchQuery('')
                                  setModalStateFilter('')
                                }}
                                className="px-2.5 py-1 text-xs font-semibold rounded-lg border transition-all cursor-pointer bg-slate-50 hover:bg-blue-50 text-[#0052CC] border-slate-200 hover:border-blue-200"
                              >
                                Xem đơn
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Detailed Tasks Section (Only for Non-Admin / Designer viewing personal finance) */}
          {!isAdmin && (
            <div className="space-y-3">
            {/* Sub-Tabs: Chưa thanh toán vs Đã thanh toán */}
            <div className="flex items-center justify-between flex-wrap gap-3 border-b border-slate-200 pb-2">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setPaymentSubTab('unpaid')
                    setCurrentPage(1)
                    setSelectedOrderIds([])
                  }}
                  className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer border ${
                    paymentSubTab === 'unpaid'
                      ? 'bg-amber-500 text-white border-amber-600 shadow-xs'
                      : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                  }`}
                >
                  <Clock className="h-4 w-4" />
                  <span>Chưa Thanh Toán</span>
                  <span className={`px-2 py-0.2 rounded-full text-[11px] font-mono ${paymentSubTab === 'unpaid' ? 'bg-amber-600 text-white' : 'bg-slate-100 text-slate-700'}`}>
                    {data?.total_unpaid_tasks ?? 0}
                  </span>
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setPaymentSubTab('paid')
                    setCurrentPage(1)
                    setSelectedOrderIds([])
                  }}
                  className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer border ${
                    paymentSubTab === 'paid'
                      ? 'bg-emerald-600 text-white border-emerald-700 shadow-xs'
                      : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                  }`}
                >
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Đã Thanh Toán</span>
                  <span className={`px-2 py-0.2 rounded-full text-[11px] font-mono ${paymentSubTab === 'paid' ? 'bg-emerald-700 text-white' : 'bg-slate-100 text-slate-700'}`}>
                    {data?.total_paid_tasks ?? 0}
                  </span>
                </button>
              </div>

              {/* Bulk Action Bar (when selected) */}
              {isAdmin && selectedOrderIds.length > 0 && (
                <div className="flex items-center gap-2 bg-blue-50 px-3 py-1.5 rounded-xl border border-blue-200 animate-in fade-in duration-150">
                  <span className="text-xs font-bold text-blue-900">
                    Đã chọn <span className="font-mono text-[#0052CC]">{selectedOrderIds.length}</span> đơn
                  </span>

                  {paymentSubTab === 'unpaid' ? (
                    <button
                      type="button"
                      disabled={processingAction}
                      onClick={() => handleMarkPaid()}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg shadow-xs transition-all disabled:opacity-50 cursor-pointer"
                    >
                      {processingAction ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CreditCard className="h-3.5 w-3.5" />}
                      <span>Xác Nhận Thanh Toán</span>
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={processingAction}
                      onClick={() => handleUnmarkPaid()}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-amber-800 bg-amber-100 hover:bg-amber-200 border border-amber-300 rounded-lg shadow-xs transition-all disabled:opacity-50 cursor-pointer"
                    >
                      {processingAction ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
                      <span>Hủy Thanh Toán</span>
                    </button>
                  )}

                  <button
                    type="button"
                    onClick={() => {
                      setSelectedOrderIds([])
                      setLastSelectedOrderIndex(null)
                    }}
                    className="text-xs text-slate-500 hover:text-slate-700 font-semibold px-2 py-1 rounded hover:bg-blue-100/50 cursor-pointer"
                  >
                    Bỏ chọn
                  </button>
                </div>
              )}
            </div>

            {/* Filter Bar */}
            <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs space-y-3">
              <div className="flex flex-col md:flex-row items-center justify-between gap-4 flex-wrap">
                <div className="relative w-full md:w-72">
                  <Search className="h-4 w-4 absolute left-3.5 top-3 text-slate-400" />
                  <input
                    type="text"
                    placeholder={isAdmin ? "Tìm mã đơn, tên sản phẩm, des..." : "Tìm tên sản phẩm..."}
                    className="w-full pl-10 pr-4 py-2 text-xs rounded-lg border border-slate-200 focus:outline-none focus:border-[#0052CC] bg-slate-50"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                  />
                </div>

                <div className="flex flex-wrap items-center gap-2.5 w-full md:w-auto">
                  {isAdmin && (
                    <div className="flex items-center gap-1.5">
                      <Users className="h-3.5 w-3.5 text-slate-400" />
                      <select
                        className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC]"
                        value={selectedDesigner}
                        onChange={(e) => {
                          setSelectedDesigner(e.target.value)
                          setCurrentPage(1)
                          setSelectedOrderIds([])
                        }}
                      >
                        <option value="">Tất cả Designer</option>
                        {data?.designers_summary.map((d) => (
                          <option key={d.designer_name} value={d.designer_id || d.designer_name}>
                            {d.designer_name} ({d.total_tasks} công)
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div className="flex items-center gap-1.5">
                    <Filter className="h-3.5 w-3.5 text-slate-400" />
                    <select
                      className="text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC]"
                      value={stateFilter}
                      onChange={(e) => {
                        setStateFilter(e.target.value)
                        setCurrentPage(1)
                        setSelectedOrderIds([])
                      }}
                    >
                      <option value="">Tất cả Trạng Thái</option>
                      <option value="REVIEW">Chờ Duyệt (Review)</option>
                      <option value="FIX">Yêu Cầu Sửa (Fix)</option>
                      <option value="DONE">Hoàn Thành (Done)</option>
                    </select>
                  </div>

                  {/* Date Filter Range */}
                  <div className="flex items-center gap-1.5 bg-slate-50 px-2.5 py-1 rounded-lg border border-slate-200">
                    <Calendar className="h-3.5 w-3.5 text-slate-400" />
                    <span className="text-xs text-slate-500 font-medium">Thời gian:</span>
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => {
                        setStartDate(e.target.value)
                        setDatePreset('')
                        setCurrentPage(1)
                        setSelectedOrderIds([])
                      }}
                      className="rounded border border-slate-200 bg-white px-2 py-1 text-xs focus:outline-none"
                    />
                    <span className="text-xs text-slate-400">-</span>
                    <input
                      type="date"
                      value={endDate}
                      onChange={(e) => {
                        setEndDate(e.target.value)
                        setDatePreset('')
                        setCurrentPage(1)
                        setSelectedOrderIds([])
                      }}
                      className="rounded border border-slate-200 bg-white px-2 py-1 text-xs focus:outline-none"
                    />
                  </div>

                  {/* Quick Date Presets */}
                  <div className="flex items-center gap-1">
                    <button
                      type="button"
                      onClick={() => applyDatePreset('today')}
                      className={`px-2 py-1 text-xs rounded-md font-semibold transition-all cursor-pointer ${
                        datePreset === 'today' ? 'bg-[#0052CC] text-white' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                      }`}
                    >
                      Hôm nay
                    </button>
                    <button
                      type="button"
                      onClick={() => applyDatePreset('yesterday')}
                      className={`px-2 py-1 text-xs rounded-md font-semibold transition-all cursor-pointer ${
                        datePreset === 'yesterday' ? 'bg-[#0052CC] text-white' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                      }`}
                    >
                      Hôm qua
                    </button>
                    <button
                      type="button"
                      onClick={() => applyDatePreset('7days')}
                      className={`px-2 py-1 text-xs rounded-md font-semibold transition-all cursor-pointer ${
                        datePreset === '7days' ? 'bg-[#0052CC] text-white' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                      }`}
                    >
                      7 ngày
                    </button>
                    <button
                      type="button"
                      onClick={() => applyDatePreset('this_month')}
                      className={`px-2 py-1 text-xs rounded-md font-semibold transition-all cursor-pointer ${
                        datePreset === 'this_month' ? 'bg-[#0052CC] text-white' : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                      }`}
                    >
                      Tháng này
                    </button>
                  </div>

                  {(selectedDesigner || stateFilter || searchQuery || startDate || endDate) && (
                    <button
                      onClick={() => {
                        setSelectedDesigner('')
                        setStateFilter('')
                        setSearchQuery('')
                        setStartDate('')
                        setEndDate('')
                        setDatePreset('')
                        setCurrentPage(1)
                        setSelectedOrderIds([])
                      }}
                      className="flex items-center gap-1 text-xs text-rose-600 hover:text-rose-700 font-bold px-2.5 py-1.5 rounded-lg hover:bg-rose-50 cursor-pointer"
                    >
                      <RotateCcw className="h-3 w-3" />
                      <span>Xóa lọc</span>
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Dense Table of Credited Tasks */}
            <div className="rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden">
              <div className="px-5 py-3.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
                <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-2">
                  <FileText className="h-4 w-4 text-[#0052CC]" />
                  <span>
                    Danh Sách Đơn {paymentSubTab === 'unpaid' ? 'Chưa Thanh Toán' : 'Đã Thanh Toán'} ({data?.total_tasks_count ?? 0})
                  </span>
                </h3>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs">
                  <thead>
                    <tr className="bg-slate-50/50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500">
                      {isAdmin && (
                        <th className="py-3 px-3 w-10 text-center">
                          <input
                            type="checkbox"
                            checked={allCurrentIdsSelected}
                            onChange={handleSelectAll}
                            className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] cursor-pointer"
                            title="Chọn tất cả đơn trên trang này"
                          />
                        </th>
                      )}
                      <th className="py-3 px-3 w-14 text-center">Ảnh</th>
                      <th className="py-3 px-4">{isAdmin ? 'Mã Đơn / Tên Sản Phẩm' : 'Tên Sản Phẩm'}</th>
                      {isAdmin && <th className="py-3 px-4">Designer</th>}
                      <th className="py-3 px-4">Trạng Thái</th>
                      <th className="py-3 px-4 whitespace-nowrap">Thời Gian Nộp Bài</th>
                      {paymentSubTab === 'paid' && (
                        <th className="py-3 px-4 whitespace-nowrap">Thời Gian Thanh Toán</th>
                      )}
                      <th className="py-3 px-4">Link Bài Nộp</th>
                      <th className="py-3 px-4 text-center">Số Lần Nộp</th>
                      <th className="py-3 px-4 text-right">Thao Tác</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {loading ? (
                      <tr>
                        <td colSpan={isAdmin ? (paymentSubTab === 'paid' ? 10 : 9) : (paymentSubTab === 'paid' ? 8 : 7)} className="py-12 text-center text-slate-400">
                          <Loader2 className="h-8 w-8 mx-auto mb-2 animate-spin opacity-50 text-[#0052CC]" />
                          <p className="font-medium text-sm text-slate-500">Đang tải danh sách đơn...</p>
                        </td>
                      </tr>
                    ) : !data?.tasks || data.tasks.length === 0 ? (
                      <tr>
                        <td colSpan={isAdmin ? (paymentSubTab === 'paid' ? 10 : 9) : (paymentSubTab === 'paid' ? 8 : 7)} className="py-12 text-center text-slate-400">
                          <Package className="h-10 w-10 mx-auto mb-2 opacity-30" />
                          <p className="font-medium text-sm text-slate-500">
                            {paymentSubTab === 'unpaid' ? 'Không có đơn nào chưa thanh toán' : 'Chưa có đơn nào đã thanh toán'}
                          </p>
                          <p className="text-xs text-slate-400 mt-1">
                            {paymentSubTab === 'unpaid'
                              ? 'Khi Designer nộp bài Review có link placeholder hợp lệ, đơn sẽ tự động xuất hiện tại đây.'
                              : 'Khi Admin xác nhận thanh toán các đơn ở tab Chưa thanh toán, các đơn sẽ chuyển sang tab này.'}
                          </p>
                        </td>
                      </tr>
                    ) : (
                      data.tasks.map((task, idx) => {
                        const isSelected = selectedOrderIds.includes(task.order_id)
                        const statusInfo = getStatusInfo(task.current_state)
                        const submitTimeSplit = formatUtc7Split(task.review_submitted_at || task.status_changed_at || task.first_submitted_at)
                        const paidTimeSplit = formatUtc7Split(task.paid_at)

                        return (
                          <tr
                            key={task.order_id}
                            className={`transition-colors hover:bg-blue-50/60 ${isSelected ? 'bg-blue-50/80' : ''}`}
                          >
                            {/* Checkbox (Admin only) with Shift + Click support */}
                            {isAdmin && (
                              <td className="py-2.5 px-3 text-center">
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onClick={(e) => handleSelectOrder(task.order_id, idx, e)}
                                  onChange={() => {}}
                                  className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] cursor-pointer"
                                />
                              </td>
                            )}

                            {/* Thumbnail */}
                            <td className="py-2.5 px-3 text-center">
                              {task.thumbnail_url ? (
                                <img
                                  src={resolveAssetUrl(task.thumbnail_url)}
                                  alt={isAdmin ? task.external_order_id : (task.product_name || 'Ảnh sản phẩm')}
                                  title="Click để phóng to"
                                  onClick={() => setSelectedImage(resolveAssetUrl(task.thumbnail_url) ?? null)}
                                  className="h-10 w-10 rounded-lg object-cover border border-slate-200 mx-auto shadow-2xs cursor-pointer hover:scale-105 transition-transform"
                                />
                              ) : (
                                <div className="h-10 w-10 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
                                  <Package className="h-5 w-5" />
                                </div>
                              )}
                            </td>

                            {/* Order Code & Product Name */}
                            <td className="py-2.5 px-4">
                              {isAdmin ? (
                                <>
                                  <div className="flex items-center gap-1.5 flex-wrap">
                                    <CopyableOrderCode code={task.external_order_id} />
                                    {task.notes_count && task.notes_count > 0 ? (
                                      <span
                                        onClick={() => {
                                          setNotesTargetFilter('order')
                                          setNotesSearch(task.external_order_id)
                                          setActiveMainTab('notes')
                                        }}
                                        className="inline-flex items-center gap-1 text-[10px] font-bold text-amber-800 bg-amber-50 border border-amber-200 px-1.5 py-0.2 rounded-full cursor-pointer hover:bg-amber-100"
                                        title="Xem ghi chú cho đơn này"
                                      >
                                        <MessageSquare className="h-2.5 w-2.5 text-amber-600" />
                                        <span>{task.notes_count} note</span>
                                      </span>
                                    ) : null}
                                  </div>
                                  {task.product_name && (
                                    <p className="text-[11px] text-slate-600 line-clamp-1 mt-0.5" title={task.product_name}>
                                      {task.product_name}
                                    </p>
                                  )}
                                </>
                              ) : (
                                <Link
                                  to={`/orders/${task.order_id}`}
                                  className="text-xs font-bold text-[#0052CC] hover:underline line-clamp-2 block"
                                  title={task.product_name || 'Đơn thiết kế'}
                                >
                                  {task.product_name || 'Đơn thiết kế'}
                                </Link>
                              )}
                            </td>

                            {/* Designer */}
                            {isAdmin && (
                              <td className="py-2.5 px-4 font-semibold text-slate-700">
                                <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-blue-50 text-[#0052CC] border border-blue-100 text-xs">
                                  {task.designer_name}
                                </span>
                              </td>
                            )}

                            {/* Current Status */}
                            <td className="py-2.5 px-4">
                              <span
                                className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold border ${
                                  statusInfo.badgeClass
                                }`}
                              >
                                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                                <span>{statusInfo.label}</span>
                              </span>
                            </td>

                            {/* Thời Gian Nộp Bài (UTC+7) Split 2 lines */}
                            <td className="py-2.5 px-4 whitespace-nowrap">
                              {submitTimeSplit ? (
                                <div className="flex flex-col leading-tight" title="Thời gian nộp bài review (UTC+7)">
                                  <span className="font-mono text-xs font-bold text-slate-800">{submitTimeSplit.time}</span>
                                  <span className="font-mono text-[11px] text-slate-500">{submitTimeSplit.date}</span>
                                </div>
                              ) : (
                                <span className="text-slate-300 font-mono text-xs">-</span>
                              )}
                            </td>

                            {/* Thời Gian Thanh Toán (UTC+7) in paid tab */}
                            {paymentSubTab === 'paid' && (
                              <td className="py-2.5 px-4 whitespace-nowrap">
                                {paidTimeSplit ? (
                                  <div className="flex flex-col leading-tight" title="Thời gian Admin xác nhận thanh toán (UTC+7)">
                                    <span className="font-mono text-xs font-bold text-emerald-700">{paidTimeSplit.time}</span>
                                    <span className="font-mono text-[11px] text-slate-500">{paidTimeSplit.date}</span>
                                  </div>
                                ) : (
                                  <span className="text-slate-300 font-mono text-xs">-</span>
                                )}
                              </td>
                            )}

                            {/* Link Bài Nộp / Placeholder */}
                            <td className="py-2.5 px-4">
                              {task.drive_link ? (() => {
                                const validUrl = resolveExternalUrl(task.drive_link)
                                return validUrl ? (
                                  <a
                                    href={validUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1 text-[11px] font-bold text-[#0052CC] hover:underline bg-blue-50 px-2 py-1 rounded border border-blue-200 max-w-[200px] truncate"
                                    title={task.drive_link}
                                  >
                                    <Check className="h-3 w-3 text-emerald-600 stroke-[3]" />
                                    <span className="truncate">{task.drive_link}</span>
                                    <ExternalLink className="h-3 w-3 shrink-0" />
                                  </a>
                                ) : (
                                  <span className="inline-flex items-center gap-1 text-[11px] font-mono font-medium text-slate-700 bg-slate-50 px-2 py-1 rounded border border-slate-200 max-w-[200px] truncate" title={task.drive_link}>
                                    <span className="truncate">{task.drive_link}</span>
                                  </span>
                                )
                              })() : (
                                <span className="inline-flex items-center gap-1 text-[10px] font-bold text-rose-700 bg-rose-50 px-1.5 py-0.5 rounded border border-rose-200">
                                  <AlertTriangle className="h-3 w-3 text-rose-600" />
                                  <span>Trống placeholder</span>
                                </span>
                              )}
                            </td>

                            {/* Submission Count */}
                            <td className="py-2.5 px-4 text-center">
                              <span className="font-mono font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                                {task.submission_count} lần
                              </span>
                            </td>

                            {/* Actions */}
                            <td className="py-2.5 px-4 text-right">
                              <div className="flex items-center justify-end gap-1.5 flex-wrap">
                                {/* Single Unmark Paid Button in Paid Tab */}
                                {isAdmin && paymentSubTab === 'paid' && (
                                  <button
                                    type="button"
                                    onClick={() => handleUnmarkPaid([task.order_id])}
                                    className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700 bg-amber-50 hover:bg-amber-100 px-2 py-1 rounded-md border border-amber-200 transition-colors cursor-pointer"
                                    title="Hủy trạng thái thanh toán cho đơn này"
                                  >
                                    <RotateCcw className="h-3 w-3 text-amber-600" />
                                    <span>Hủy</span>
                                  </button>
                                )}

                                {/* Single Mark Paid Button in Unpaid Tab */}
                                {isAdmin && paymentSubTab === 'unpaid' && (
                                  <button
                                    type="button"
                                    onClick={() => handleMarkPaid([task.order_id])}
                                    className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 px-2 py-1 rounded-md border border-emerald-200 transition-colors cursor-pointer"
                                    title="Xác nhận thanh toán cho đơn này"
                                  >
                                    <CreditCard className="h-3 w-3 text-emerald-600" />
                                    <span>Trả</span>
                                  </button>
                                )}

                                {/* Timeline History Button */}
                                <button
                                  type="button"
                                  onClick={() => setTimelineOrder({ id: task.order_id, code: task.external_order_id, name: task.product_name })}
                                  className="inline-flex items-center gap-1 text-xs font-bold text-slate-700 bg-slate-100 hover:bg-blue-50 hover:text-[#0052CC] px-2 py-1 rounded-md border border-slate-200 transition-colors cursor-pointer"
                                  title="Xem toàn bộ lịch sử Timeline chuyển trạng thái"
                                >
                                  <History className="h-3.5 w-3.5 text-slate-500" />
                                  <span>Timeline</span>
                                </button>

                                {/* Admin Quick Note Button */}
                                {isAdmin && (
                                  <button
                                    type="button"
                                    onClick={() => openAddNoteModal('order', task.order_id, task.external_order_id)}
                                    className="inline-flex items-center gap-1 text-xs font-bold text-slate-700 bg-slate-100 hover:bg-amber-50 hover:text-amber-800 hover:border-amber-200 px-2 py-1 rounded-md border border-slate-200 transition-colors cursor-pointer"
                                    title="Thêm ghi chú cho đơn hàng này"
                                  >
                                    <Plus className="h-3 w-3 text-slate-500" />
                                    <span>Note</span>
                                  </button>
                                )}

                                {/* Detail Link */}
                                <Link
                                  to={`/orders/${task.order_id}`}
                                  className="inline-flex items-center gap-1 text-xs font-semibold text-[#0052CC] hover:text-[#003D99] hover:bg-blue-50 px-2 py-1 rounded-md transition-colors"
                                  title="Xem trang chi tiết đơn hàng"
                                >
                                  <span>Chi tiết</span>
                                  <ChevronRight className="h-3.5 w-3.5" />
                                </Link>
                              </div>
                            </td>
                          </tr>
                        )
                      })
                    )}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {data && data.total_tasks_count > 0 && (
                <Pagination
                  totalItems={data.total_tasks_count}
                  currentPage={currentPage}
                  pageSize={50}
                  onPageChange={setCurrentPage}
                />
              )}
            </div>
          </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* TAB 2: ADMIN NOTES MANAGEMENT                                             */}
      {/* ========================================================================= */}
      {activeMainTab === 'notes' && (
        <div className="space-y-4">
          {/* Notes Top Control Bar */}
          <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-xs flex flex-col md:flex-row items-center justify-between gap-4 flex-wrap">
            <div className="flex items-center gap-3 flex-wrap w-full md:w-auto">
              <div className="relative w-full md:w-64">
                <Search className="h-4 w-4 absolute left-3.5 top-3 text-slate-400" />
                <input
                  type="text"
                  placeholder="Tìm nội dung note, mã đơn, tên des..."
                  className="w-full pl-10 pr-4 py-2 text-xs rounded-lg border border-slate-200 focus:outline-none focus:border-[#0052CC] bg-slate-50"
                  value={notesSearch}
                  onChange={(e) => setNotesSearch(e.target.value)}
                />
              </div>

              {/* Target Type Filter */}
              <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-lg border border-slate-200">
                <button
                  type="button"
                  onClick={() => { setNotesTargetFilter('all'); setNotesPage(1) }}
                  className={`px-3 py-1 text-xs font-bold rounded-md transition-all cursor-pointer ${
                    notesTargetFilter === 'all' ? 'bg-white text-[#0052CC] shadow-2xs' : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  Tất cả ({notesData?.total ?? 0})
                </button>
                <button
                  type="button"
                  onClick={() => { setNotesTargetFilter('order'); setNotesPage(1) }}
                  className={`px-3 py-1 text-xs font-bold rounded-md transition-all cursor-pointer ${
                    notesTargetFilter === 'order' ? 'bg-white text-[#0052CC] shadow-2xs' : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  Note Đơn Hàng
                </button>
                <button
                  type="button"
                  onClick={() => { setNotesTargetFilter('designer'); setNotesPage(1) }}
                  className={`px-3 py-1 text-xs font-bold rounded-md transition-all cursor-pointer ${
                    notesTargetFilter === 'designer' ? 'bg-white text-[#0052CC] shadow-2xs' : 'text-slate-600 hover:text-slate-900'
                  }`}
                >
                  Note Designer
                </button>
              </div>

              {/* Reset Notes Filter */}
              {(notesSearch || notesTargetFilter !== 'all' || notesDesignerFilter) && (
                <button
                  onClick={() => {
                    setNotesSearch('')
                    setNotesTargetFilter('all')
                    setNotesDesignerFilter('')
                    setNotesPage(1)
                  }}
                  className="flex items-center gap-1 text-xs text-rose-600 hover:text-rose-700 font-bold px-2.5 py-1.5 rounded-lg hover:bg-rose-50 cursor-pointer"
                >
                  <RotateCcw className="h-3 w-3" />
                  <span>Xóa lọc</span>
                </button>
              )}
            </div>

            {/* Create New Note Button */}
            {isAdmin && (
              <button
                type="button"
                onClick={() => openAddNoteModal('order')}
                className="inline-flex items-center gap-1.5 px-3.5 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#003D99] rounded-lg shadow-sm transition-all cursor-pointer"
              >
                <Plus className="h-4 w-4" />
                <span>Tạo Ghi Chú Mới</span>
              </button>
            )}
          </div>

          {/* Notes List Table */}
          <div className="rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-xs">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500">
                    <th className="py-3 px-4 w-40">Đối Tượng Note</th>
                    <th className="py-3 px-4">Nội Dung Ghi Chú</th>
                    <th className="py-3 px-4 w-36">Người Tạo</th>
                    <th className="py-3 px-4 w-36 whitespace-nowrap">Thời Gian (UTC+7)</th>
                    {isAdmin && <th className="py-3 px-4 w-28 text-right">Thao Tác</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {notesLoading ? (
                    <tr>
                      <td colSpan={isAdmin ? 5 : 4} className="py-12 text-center text-slate-400">
                        <Loader2 className="h-8 w-8 mx-auto mb-2 animate-spin opacity-50 text-[#0052CC]" />
                        <p className="font-medium text-sm text-slate-500">Đang tải danh sách ghi chú…</p>
                      </td>
                    </tr>
                  ) : !notesData?.notes || notesData.notes.length === 0 ? (
                    <tr>
                      <td colSpan={isAdmin ? 5 : 4} className="py-12 text-center text-slate-400">
                        <MessageSquare className="h-10 w-10 mx-auto mb-2 opacity-30" />
                        <p className="font-medium text-sm text-slate-500">Chưa có ghi chú nào</p>
                        <p className="text-xs text-slate-400 mt-1">Admin có thể bấm "+ Tạo Ghi Chú Mới" để ghi lại trao đổi hoặc lưu ý cho đơn hàng / Designer.</p>
                      </td>
                    </tr>
                  ) : (
                    notesData.notes.map((note) => {
                      const noteSplit = formatUtc7Split(note.created_at)

                      return (
                        <tr key={note.id} className="transition-colors hover:bg-slate-50/70">
                          {/* Target Type & Code */}
                          <td className="py-3 px-4">
                            {note.target_type === 'order' ? (
                              <div className="space-y-1">
                                <span className="inline-flex items-center gap-1 text-[10px] font-bold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded">
                                  <span>Đơn Hàng</span>
                                </span>
                                {note.order_code ? (
                                  <div>
                                    <CopyableOrderCode code={note.order_code} />
                                  </div>
                                ) : (
                                  <span className="text-slate-400 text-xs italic">Không rõ mã</span>
                                )}
                              </div>
                            ) : (
                              <div className="space-y-1">
                                <span className="inline-flex items-center gap-1 text-[10px] font-bold text-purple-700 bg-purple-50 border border-purple-200 px-2 py-0.5 rounded">
                                  <span>Designer</span>
                                </span>
                                <p className="font-semibold text-slate-800 text-xs">{note.designer_name || 'Designer'}</p>
                              </div>
                            )}
                          </td>

                          {/* Note Content */}
                          <td className="py-3 px-4">
                            <p className="text-xs text-slate-800 whitespace-pre-wrap leading-relaxed font-normal">
                              {note.content}
                            </p>
                          </td>

                          {/* Author */}
                          <td className="py-3 px-4 text-slate-600 font-medium text-xs">
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 text-slate-700 text-[11px] font-semibold">
                              {note.author_name}
                            </span>
                          </td>

                          {/* Created At (2 lines) */}
                          <td className="py-3 px-4 whitespace-nowrap">
                            {noteSplit ? (
                              <div className="flex flex-col leading-tight">
                                <span className="font-mono text-xs font-bold text-slate-800">{noteSplit.time}</span>
                                <span className="font-mono text-[11px] text-slate-500">{noteSplit.date}</span>
                              </div>
                            ) : (
                              <span className="text-slate-400 font-mono text-xs">-</span>
                            )}
                          </td>

                          {/* Actions */}
                          {isAdmin && (
                            <td className="py-3 px-4 text-right">
                              <div className="flex items-center justify-end gap-1">
                                <button
                                  type="button"
                                  onClick={() => openEditNoteModal(note)}
                                  className="p-1.5 text-slate-500 hover:text-[#0052CC] hover:bg-blue-50 rounded-lg transition-colors cursor-pointer"
                                  title="Chỉnh sửa ghi chú"
                                >
                                  <Edit2 className="h-3.5 w-3.5" />
                                </button>
                                <button
                                  type="button"
                                  onClick={() => handleDeleteNote(note.id)}
                                  className="p-1.5 text-slate-500 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition-colors cursor-pointer"
                                  title="Xóa ghi chú"
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
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

            {/* Notes Pagination */}
            {notesData && notesData.total > 0 && (
              <Pagination
                totalItems={notesData.total}
                currentPage={notesPage}
                pageSize={50}
                onPageChange={setNotesPage}
              />
            )}
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: EXPORT EXCEL                                                       */}
      {/* ========================================================================= */}
      {exportModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl border border-slate-200 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                <Download className="h-4 w-4 text-emerald-600" />
                <span>Xuất Báo Cáo Tài Chính & Bài Nộp Ra Excel</span>
              </h3>
              <button
                type="button"
                onClick={() => setExportModalOpen(false)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <p className="text-xs text-slate-500">
              File Excel (.csv UTF-8) sẽ bao gồm đầy đủ 3 cột chính: <strong>Mã Đơn</strong>, <strong>Link Sản Phẩm (Bài Nộp của Des)</strong>, <strong>Tên Designer</strong>, cùng thời gian nộp bài và thời gian thanh toán.
            </p>

            <div className="space-y-3 pt-2">
              {/* Designer Filter */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Chọn Designer:</label>
                <select
                  value={exportDesignerId}
                  onChange={(e) => setExportDesignerId(e.target.value)}
                  className="w-full text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 focus:bg-white focus:outline-none focus:border-[#0052CC]"
                >
                  <option value="ALL">Tất cả Designer</option>
                  {data?.designers_summary.map((d) => (
                    <option key={d.designer_name} value={d.designer_id || d.designer_name}>
                      {d.designer_name} ({d.total_tasks} công)
                    </option>
                  ))}
                </select>
              </div>

              {/* Payment Status Filter */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Trạng Thái Thanh Toán:</label>
                <select
                  value={exportPaymentStatus}
                  onChange={(e) => setExportPaymentStatus(e.target.value as any)}
                  className="w-full text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 focus:bg-white focus:outline-none focus:border-[#0052CC]"
                >
                  <option value="all">Tất cả đơn (Chưa & Đã thanh toán)</option>
                  <option value="unpaid">Chỉ đơn Chưa thanh toán</option>
                  <option value="paid">Chỉ đơn Đã thanh toán</option>
                </select>
              </div>

              {/* Date Range */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 mb-1">Khoảng Thời Gian Nộp / Tính Công:</label>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-[11px] text-slate-500 block mb-0.5">Từ ngày:</span>
                    <input
                      type="date"
                      value={exportStartDate}
                      onChange={(e) => setExportStartDate(e.target.value)}
                      className="w-full text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-slate-50 focus:bg-white focus:outline-none focus:border-[#0052CC]"
                    />
                  </div>
                  <div>
                    <span className="text-[11px] text-slate-500 block mb-0.5">Đến ngày:</span>
                    <input
                      type="date"
                      value={exportEndDate}
                      onChange={(e) => setExportEndDate(e.target.value)}
                      className="w-full text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-slate-50 focus:bg-white focus:outline-none focus:border-[#0052CC]"
                    />
                  </div>
                </div>
              </div>

              {/* Presets */}
              <div className="flex items-center gap-1.5 pt-1">
                <span className="text-[11px] text-slate-400">Chọn nhanh:</span>
                <button
                  type="button"
                  onClick={() => {
                    const now = new Date()
                    const firstDay = new Date(now.getFullYear(), now.getMonth(), 1)
                    setExportStartDate(firstDay.toISOString().slice(0, 10))
                    setExportEndDate(now.toISOString().slice(0, 10))
                  }}
                  className="px-2 py-0.5 text-[11px] rounded bg-slate-100 hover:bg-slate-200 text-slate-700 cursor-pointer"
                >
                  Tháng này
                </button>
                <button
                  type="button"
                  onClick={() => {
                    const now = new Date()
                    const past = new Date(now)
                    past.setDate(past.getDate() - 6)
                    setExportStartDate(past.toISOString().slice(0, 10))
                    setExportEndDate(now.toISOString().slice(0, 10))
                  }}
                  className="px-2 py-0.5 text-[11px] rounded bg-slate-100 hover:bg-slate-200 text-slate-700 cursor-pointer"
                >
                  7 ngày qua
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setExportStartDate('')
                    setExportEndDate('')
                  }}
                  className="px-2 py-0.5 text-[11px] rounded bg-slate-100 hover:bg-slate-200 text-slate-700 cursor-pointer"
                >
                  Toàn bộ
                </button>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setExportModalOpen(false)}
                className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={handleDownloadExcel}
                disabled={exporting}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-lg shadow-sm transition-all disabled:opacity-50 cursor-pointer"
              >
                {exporting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                <span>Xác Nhận Xuất Excel</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: ADD / EDIT NOTE                                                    */}
      {/* ========================================================================= */}
      {noteModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl border border-slate-200 space-y-4">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                <MessageSquare className="h-4 w-4 text-[#0052CC]" />
                <span>{editingNote ? 'Chỉnh Sửa Ghi Chú' : 'Thêm Ghi Chú Mới (Admin)'}</span>
              </h3>
              <button
                type="button"
                onClick={() => setNoteModalOpen(false)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600 cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {!editingNote && (
              <div className="space-y-3">
                <label className="block text-xs font-semibold text-slate-700">Loại Ghi Chú:</label>
                <div className="flex items-center gap-3">
                  <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer">
                    <input
                      type="radio"
                      name="noteTarget"
                      checked={noteTargetType === 'order'}
                      onChange={() => setNoteTargetType('order')}
                      className="text-[#0052CC] focus:ring-[#0052CC]"
                    />
                    <span>Ghi chú cho Đơn Hàng</span>
                  </label>
                  <label className="flex items-center gap-2 text-xs font-semibold cursor-pointer">
                    <input
                      type="radio"
                      name="noteTarget"
                      checked={noteTargetType === 'designer'}
                      onChange={() => setNoteTargetType('designer')}
                      className="text-[#0052CC] focus:ring-[#0052CC]"
                    />
                    <span>Ghi chú cho Designer</span>
                  </label>
                </div>

                {noteTargetType === 'order' ? (
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">Mã Đơn Hàng:</label>
                    <input
                      type="text"
                      placeholder="Nhập mã đơn hàng (ví dụ: PRN-12345)"
                      value={noteOrderCode}
                      onChange={(e) => setNoteOrderCode(e.target.value)}
                      className="w-full text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 focus:bg-white focus:outline-none focus:border-[#0052CC]"
                    />
                  </div>
                ) : (
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">Chọn Designer:</label>
                    {data?.designers_summary && data.designers_summary.length > 0 ? (
                      <select
                        value={noteDesignerId || noteDesignerName}
                        onChange={(e) => {
                          const val = e.target.value
                          const found = data.designers_summary.find((d) => (d.designer_id || d.designer_name) === val)
                          if (found) {
                            setNoteDesignerId(found.designer_id || '')
                            setNoteDesignerName(found.designer_name)
                          } else {
                            setNoteDesignerName(val)
                          }
                        }}
                        className="w-full text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 font-medium focus:bg-white focus:outline-none focus:border-[#0052CC]"
                      >
                        <option value="">-- Chọn Designer --</option>
                        {data.designers_summary.map((d) => (
                          <option key={d.designer_name} value={d.designer_id || d.designer_name}>
                            {d.designer_name} ({d.total_tasks} công)
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        placeholder="Nhập tên Designer"
                        value={noteDesignerName}
                        onChange={(e) => setNoteDesignerName(e.target.value)}
                        className="w-full text-xs border border-slate-200 rounded-lg px-3 py-2 bg-slate-50 focus:bg-white focus:outline-none focus:border-[#0052CC]"
                      />
                    )}
                  </div>
                )}
              </div>
            )}

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1">Nội Dung Ghi Chú:</label>
              <textarea
                rows={4}
                placeholder="Nhập nội dung ghi chú, đánh giá chất lượng, ghi nhận đặc biệt hoặc lưu ý thanh toán..."
                value={noteContent}
                onChange={(e) => setNoteContent(e.target.value)}
                className="w-full text-xs border border-slate-200 rounded-lg p-3 bg-slate-50 focus:bg-white focus:outline-none focus:border-[#0052CC]"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setNoteModalOpen(false)}
                className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-lg cursor-pointer"
              >
                Hủy
              </button>
              <button
                type="button"
                onClick={handleSaveNote}
                disabled={noteSaving || !noteContent.trim()}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#003D99] rounded-lg shadow-sm transition-all disabled:opacity-50 cursor-pointer"
              >
                {noteSaving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5 stroke-[3]" />}
                <span>{editingNote ? 'Cập Nhật' : 'Lưu Ghi Chú'}</span>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL: DESIGNER DETAIL TASKS & FINANCE (ADMIN)                            */}
      {/* ========================================================================= */}
      {selectedDesignerForModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4 animate-in fade-in duration-150">
          <div className="w-full max-w-6xl max-h-[92vh] flex flex-col rounded-2xl bg-white shadow-2xl border border-slate-200 overflow-hidden">
            {/* Modal Header */}
            <div className="px-6 py-4 bg-slate-50 border-b border-slate-200 flex items-center justify-between flex-wrap gap-3">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-blue-100 text-[#0052CC] font-bold flex items-center justify-center text-sm">
                  {selectedDesignerForModal.designer_name.charAt(0).toUpperCase()}
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900 flex items-center gap-2">
                    <span>{selectedDesignerForModal.designer_name}</span>
                    {selectedDesignerForModal.username && (
                      <span className="text-xs text-slate-400 font-normal">@{selectedDesignerForModal.username}</span>
                    )}
                  </h3>
                  <p className="text-xs text-slate-500">
                    Chi tiết các đơn hàng & tính công cho Designer
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  title="Đóng popup"
                  onClick={() => setSelectedDesignerForModal(null)}
                  className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-200 hover:text-slate-600 transition-colors cursor-pointer"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {/* Top Controls: Sub-tabs & Bulk Actions */}
              <div className="flex items-center justify-between flex-wrap gap-3 border-b border-slate-200 pb-3">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setModalPaymentTab('unpaid')
                      setModalPage(1)
                      setModalSelectedOrderIds([])
                    }}
                    className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer border ${
                      modalPaymentTab === 'unpaid'
                        ? 'bg-amber-500 text-white border-amber-600 shadow-xs'
                        : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                    }`}
                  >
                    <Clock className="h-3.5 w-3.5" />
                    <span>Chưa Thanh Toán</span>
                    <span className={`px-2 py-0.2 rounded-full text-[11px] font-mono ${modalPaymentTab === 'unpaid' ? 'bg-amber-600 text-white' : 'bg-slate-100 text-slate-700'}`}>
                      {selectedDesignerForModal.unpaid_tasks ?? 0}
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setModalPaymentTab('paid')
                      setModalPage(1)
                      setModalSelectedOrderIds([])
                    }}
                    className={`inline-flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer border ${
                      modalPaymentTab === 'paid'
                        ? 'bg-emerald-600 text-white border-emerald-700 shadow-xs'
                        : 'bg-white text-slate-700 border-slate-200 hover:bg-slate-50'
                    }`}
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    <span>Đã Thanh Toán</span>
                    <span className={`px-2 py-0.2 rounded-full text-[11px] font-mono ${modalPaymentTab === 'paid' ? 'bg-emerald-700 text-white' : 'bg-slate-100 text-slate-700'}`}>
                      {selectedDesignerForModal.paid_tasks ?? 0}
                    </span>
                  </button>
                </div>

                {/* Top Payment Action Button & Selection Indicator */}
                <div className="flex items-center gap-2 flex-wrap">
                  {modalSelectedOrderIds.length > 0 ? (
                    <div className="flex items-center gap-2 bg-blue-50 px-3 py-1.5 rounded-xl border border-blue-200 animate-in fade-in duration-150">
                      <span className="text-xs font-bold text-blue-900">
                        Đã chọn <span className="font-mono text-[#0052CC]">{modalSelectedOrderIds.length}</span> đơn
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          setModalSelectedOrderIds([])
                          setModalLastSelectedIndex(null)
                        }}
                        className="text-xs text-slate-500 hover:text-slate-700 font-semibold px-1.5 py-0.5 rounded hover:bg-blue-100/50 cursor-pointer"
                      >
                        Bỏ chọn
                      </button>
                    </div>
                  ) : null}

                  {modalPaymentTab === 'unpaid' ? (
                    <button
                      type="button"
                      disabled={processingAction || modalTasks.length === 0}
                      onClick={() => handleModalMarkPaid()}
                      className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 active:scale-95 rounded-xl shadow-xs transition-all disabled:opacity-50 cursor-pointer"
                    >
                      {processingAction ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <CreditCard className="h-3.5 w-3.5" />}
                      <span>
                        {modalSelectedOrderIds.length > 0
                          ? `Xác Nhận Thanh Toán (${modalSelectedOrderIds.length} Đơn Đã Chọn)`
                          : `Xác Nhận Thanh Toán (${modalTasks.length} Đơn)`}
                      </span>
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={processingAction || modalTasks.length === 0}
                      onClick={() => handleModalUnmarkPaid()}
                      className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-amber-800 bg-amber-100 hover:bg-amber-200 border border-amber-300 active:scale-95 rounded-xl shadow-xs transition-all disabled:opacity-50 cursor-pointer"
                    >
                      {processingAction ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
                      <span>
                        {modalSelectedOrderIds.length > 0
                          ? `Hủy Thanh Toán (${modalSelectedOrderIds.length} Đơn Đã Chọn)`
                          : `Hủy Thanh Toán (${modalTasks.length} Đơn)`}
                      </span>
                    </button>
                  )}
                </div>
              </div>

              {/* Filter Bar inside Modal */}
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <div className="relative w-full sm:w-64">
                  <Search className="h-4 w-4 absolute left-3 top-2.5 text-slate-400" />
                  <input
                    type="text"
                    placeholder="Tìm mã đơn, tên sản phẩm..."
                    className="w-full pl-9 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 focus:outline-none focus:border-[#0052CC] bg-slate-50"
                    value={modalSearchQuery}
                    onChange={(e) => setModalSearchQuery(e.target.value)}
                  />
                </div>

                <div className="flex items-center gap-2">
                  <select
                    className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-slate-50 font-medium focus:outline-none focus:border-[#0052CC]"
                    value={modalStateFilter}
                    onChange={(e) => {
                      setModalStateFilter(e.target.value)
                      setModalPage(1)
                      setModalSelectedOrderIds([])
                    }}
                  >
                    <option value="">Tất cả Trạng Thái</option>
                    <option value="REVIEW">Chờ duyệt (Review)</option>
                    <option value="FIX">Cần sửa (Fix)</option>
                    <option value="DONE">Hoàn thành (Done)</option>
                  </select>

                  {(modalSearchQuery || modalStateFilter) && (
                    <button
                      type="button"
                      onClick={() => {
                        setModalSearchQuery('')
                        setModalStateFilter('')
                        setModalPage(1)
                        setModalSelectedOrderIds([])
                      }}
                      className="flex items-center gap-1 text-xs text-rose-600 hover:text-rose-700 font-bold px-2 py-1 rounded-lg hover:bg-rose-50 cursor-pointer"
                    >
                      <RotateCcw className="h-3 w-3" />
                      <span>Xóa lọc</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Dynamic Total Summary Banner */}
              <div className="bg-gradient-to-r from-blue-50 via-indigo-50/50 to-emerald-50/40 border border-blue-200 rounded-xl p-3.5 flex items-center justify-between flex-wrap gap-3 shadow-2xs">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="text-xs text-slate-600 font-medium">Số lượng đơn:</span>
                  <span className="font-mono font-bold text-slate-900 bg-white px-2.5 py-0.5 rounded border border-slate-200 text-xs shadow-2xs">
                    {modalTasks.length} / {selectedDesignerForModal.total_tasks} đơn hiển thị
                  </span>
                  {modalSelectedOrderIds.length > 0 && (
                    <span className="font-mono font-bold text-[#0052CC] bg-blue-100 px-2.5 py-0.5 rounded text-xs border border-blue-200">
                      {modalSelectedOrderIds.length} đơn được chọn
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-3.5 flex-wrap">
                  {modalSelectedOrderIds.length > 0 && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-blue-900">Tổng tiền đã chọn:</span>
                      <span className="font-mono text-sm font-extrabold text-[#0052CC] bg-white px-2.5 py-1 rounded-lg border border-blue-200 shadow-2xs">
                        {modalTasks
                          .filter((t) => modalSelectedOrderIds.includes(t.order_id))
                          .reduce((sum, t) => sum + (orderRates[t.order_id] ?? 40000), 0)
                          .toLocaleString('vi-VN')} đ
                      </span>
                    </div>
                  )}
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-slate-700">
                      Tổng số tiền ({modalPaymentTab === 'unpaid' ? 'Chưa thanh toán' : 'Đã thanh toán'}):
                    </span>
                    <span className="font-mono text-base font-extrabold text-emerald-700 bg-white px-3 py-1 rounded-lg border border-emerald-300 shadow-2xs">
                      {modalTasks
                        .reduce((sum, t) => sum + (orderRates[t.order_id] ?? 40000), 0)
                        .toLocaleString('vi-VN')} đ
                    </span>
                  </div>

                  {modalPaymentTab === 'unpaid' ? (
                    <button
                      type="button"
                      disabled={processingAction || modalTasks.length === 0}
                      onClick={() => handleModalMarkPaid()}
                      className="inline-flex items-center gap-2 px-4 py-2 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 active:scale-95 rounded-xl shadow-sm transition-all disabled:opacity-50 cursor-pointer"
                    >
                      {processingAction ? <Loader2 className="h-4 w-4 animate-spin" /> : <CreditCard className="h-4 w-4" />}
                      <span>
                        {modalSelectedOrderIds.length > 0
                          ? `Thanh Toán (${modalSelectedOrderIds.length} Đơn)`
                          : `Thanh Toán Toàn Bộ (${modalTasks.length} Đơn)`}
                      </span>
                    </button>
                  ) : (
                    <button
                      type="button"
                      disabled={processingAction || modalTasks.length === 0}
                      onClick={() => handleModalUnmarkPaid()}
                      className="inline-flex items-center gap-2 px-4 py-2 text-xs font-bold text-amber-800 bg-amber-100 hover:bg-amber-200 border border-amber-300 active:scale-95 rounded-xl shadow-sm transition-all disabled:opacity-50 cursor-pointer"
                    >
                      {processingAction ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                      <span>
                        {modalSelectedOrderIds.length > 0
                          ? `Hủy Thanh Toán (${modalSelectedOrderIds.length} Đơn)`
                          : `Hủy Thanh Toán Toàn Bộ (${modalTasks.length} Đơn)`}
                      </span>
                    </button>
                  )}
                </div>
              </div>

              {/* Modal Tasks Table */}
              <div className="rounded-xl border border-slate-200 bg-white shadow-xs overflow-hidden">
                <div className="overflow-x-auto">
                  <table className="w-full text-left border-collapse text-xs">
                    <thead>
                      <tr className="bg-slate-50/70 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500">
                        <th className="py-3 px-3 w-10 text-center">
                          <input
                            type="checkbox"
                            checked={
                              modalTasks.length > 0 &&
                              modalTasks.every((t) => modalSelectedOrderIds.includes(t.order_id))
                            }
                            onChange={handleModalSelectAll}
                            className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] cursor-pointer"
                            title="Chọn tất cả đơn trên trang này"
                          />
                        </th>
                        <th className="py-3 px-3 w-12 text-center">Ảnh</th>
                        <th className="py-3 px-4">Mã Đơn / Tên Sản Phẩm</th>
                        <th className="py-3 px-4">Trạng Thái</th>
                        <th className="py-3 px-4 whitespace-nowrap">Thời Gian Nộp</th>
                        {modalPaymentTab === 'paid' && (
                          <th className="py-3 px-4 whitespace-nowrap">Thời Gian Thanh Toán</th>
                        )}
                        <th className="py-3 px-4">Link Bài Nộp</th>
                        <th className="py-3 px-3 text-center">Số Lần Nộp</th>
                        <th className="py-3 px-4 text-center">Giá Tiền (VNĐ)</th>
                        <th className="py-3 px-4 text-right">Thao Tác</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {modalTasksLoading ? (
                        <tr>
                          <td colSpan={modalPaymentTab === 'paid' ? 10 : 9} className="py-12 text-center text-slate-400">
                            <Loader2 className="h-7 w-7 mx-auto mb-2 animate-spin opacity-50 text-[#0052CC]" />
                            <p className="font-medium text-xs text-slate-500">Đang tải danh sách đơn...</p>
                          </td>
                        </tr>
                      ) : modalTasks.length === 0 ? (
                        <tr>
                          <td colSpan={modalPaymentTab === 'paid' ? 10 : 9} className="py-12 text-center text-slate-400">
                            <Package className="h-8 w-8 mx-auto mb-2 opacity-30" />
                            <p className="font-medium text-xs text-slate-500">
                              {modalPaymentTab === 'unpaid' ? 'Không có đơn nào chưa thanh toán' : 'Chưa có đơn nào đã thanh toán'}
                            </p>
                          </td>
                        </tr>
                      ) : (
                        modalTasks.map((task, idx) => {
                          const isSelected = modalSelectedOrderIds.includes(task.order_id)
                          const statusInfo = getStatusInfo(task.current_state)
                          const submitTimeSplit = formatUtc7Split(task.review_submitted_at || task.status_changed_at || task.first_submitted_at)
                          const paidTimeSplit = formatUtc7Split(task.paid_at)
                          const currentRate = orderRates[task.order_id] ?? 40000

                          return (
                            <tr
                              key={task.order_id}
                              className={`transition-colors hover:bg-blue-50/50 ${isSelected ? 'bg-blue-50/70' : ''}`}
                            >
                              <td className="py-2.5 px-3 text-center">
                                <input
                                  type="checkbox"
                                  checked={isSelected}
                                  onClick={(e) => handleModalSelectOrder(task.order_id, idx, e)}
                                  onChange={() => {}}
                                  className="rounded border-slate-300 text-[#0052CC] focus:ring-[#0052CC] cursor-pointer"
                                />
                              </td>
                              <td className="py-2.5 px-3 text-center">
                                {task.thumbnail_url ? (
                                  <img
                                    src={resolveAssetUrl(task.thumbnail_url)}
                                    alt={task.external_order_id}
                                    title="Click để phóng to"
                                    onClick={() => setSelectedImage(resolveAssetUrl(task.thumbnail_url) ?? null)}
                                    className="h-9 w-9 rounded-lg object-cover border border-slate-200 mx-auto shadow-2xs cursor-pointer hover:scale-105 transition-transform"
                                  />
                                ) : (
                                  <div className="h-9 w-9 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center mx-auto text-slate-400">
                                    <Package className="h-4 w-4" />
                                  </div>
                                )}
                              </td>
                              <td className="py-2.5 px-4">
                                <div className="flex items-center gap-1.5 flex-wrap">
                                  <CopyableOrderCode code={task.external_order_id} />
                                  {task.notes_count && task.notes_count > 0 ? (
                                    <span
                                      onClick={() => {
                                        setSelectedDesignerForModal(null)
                                        setNotesTargetFilter('order')
                                        setNotesSearch(task.external_order_id)
                                        setActiveMainTab('notes')
                                      }}
                                      className="inline-flex items-center gap-1 text-[10px] font-bold text-amber-800 bg-amber-50 border border-amber-200 px-1.5 py-0.2 rounded-full cursor-pointer hover:bg-amber-100"
                                      title="Xem ghi chú cho đơn này"
                                    >
                                      <MessageSquare className="h-2.5 w-2.5 text-amber-600" />
                                      <span>{task.notes_count} note</span>
                                    </span>
                                  ) : null}
                                </div>
                                {task.product_name && (
                                  <p className="text-[11px] text-slate-600 line-clamp-1 mt-0.5" title={task.product_name}>
                                    {task.product_name}
                                  </p>
                                )}
                              </td>
                              <td className="py-2.5 px-4">
                                <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-semibold border ${statusInfo.badgeClass}`}>
                                  <span className="h-1.5 w-1.5 rounded-full bg-current" />
                                  <span>{statusInfo.label}</span>
                                </span>
                              </td>
                              <td className="py-2.5 px-4 whitespace-nowrap">
                                {submitTimeSplit ? (
                                  <div className="flex flex-col leading-tight">
                                    <span className="font-mono text-xs font-bold text-slate-800">{submitTimeSplit.time}</span>
                                    <span className="font-mono text-[11px] text-slate-500">{submitTimeSplit.date}</span>
                                  </div>
                                ) : (
                                  <span className="text-slate-300 font-mono text-xs">-</span>
                                )}
                              </td>
                              {modalPaymentTab === 'paid' && (
                                <td className="py-2.5 px-4 whitespace-nowrap">
                                  {paidTimeSplit ? (
                                    <div className="flex flex-col leading-tight">
                                      <span className="font-mono text-xs font-bold text-emerald-700">{paidTimeSplit.time}</span>
                                      <span className="font-mono text-[11px] text-slate-500">{paidTimeSplit.date}</span>
                                    </div>
                                  ) : (
                                    <span className="text-slate-300 font-mono text-xs">-</span>
                                  )}
                                </td>
                              )}
                              <td className="py-2.5 px-4">
                                {task.drive_link ? (() => {
                                  const validUrl = resolveExternalUrl(task.drive_link)
                                  return validUrl ? (
                                    <a
                                      href={validUrl}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="inline-flex items-center gap-1 text-[11px] font-bold text-[#0052CC] hover:underline bg-blue-50 px-2 py-1 rounded border border-blue-200 max-w-[180px] truncate"
                                      title={task.drive_link}
                                    >
                                      <Check className="h-3 w-3 text-emerald-600 stroke-[3]" />
                                      <span className="truncate">{task.drive_link}</span>
                                      <ExternalLink className="h-3 w-3 shrink-0" />
                                    </a>
                                  ) : (
                                    <span className="inline-flex items-center gap-1 text-[11px] font-mono font-medium text-slate-700 bg-slate-50 px-2 py-1 rounded border border-slate-200 max-w-[180px] truncate" title={task.drive_link}>
                                      <span className="truncate">{task.drive_link}</span>
                                    </span>
                                  )
                                })() : (
                                  <span className="inline-flex items-center gap-1 text-[10px] font-bold text-rose-700 bg-rose-50 px-1.5 py-0.5 rounded border border-rose-200">
                                    <AlertTriangle className="h-3 w-3 text-rose-600" />
                                    <span>Trống placeholder</span>
                                  </span>
                                )}
                              </td>
                              <td className="py-2.5 px-3 text-center">
                                <span className="font-mono font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                                  {task.submission_count} lần
                                </span>
                              </td>
                              <td className="py-2.5 px-3 text-center whitespace-nowrap">
                                <div className="inline-flex items-center gap-1 bg-slate-50 p-1 rounded-lg border border-slate-200">
                                  <button
                                    type="button"
                                    onClick={() => handleRateChange(task.order_id, -5000)}
                                    className="w-5 h-5 rounded bg-white hover:bg-slate-200 text-slate-700 font-bold flex items-center justify-center text-xs shadow-2xs border border-slate-200 cursor-pointer active:scale-95 transition-all"
                                    title="Giảm 5,000 đ"
                                  >
                                    -
                                  </button>
                                  <span className="font-mono text-xs font-bold text-slate-800 min-w-[62px] text-center px-0.5">
                                    {currentRate.toLocaleString('vi-VN')} đ
                                  </span>
                                  <button
                                    type="button"
                                    onClick={() => handleRateChange(task.order_id, 5000)}
                                    className="w-5 h-5 rounded bg-white hover:bg-slate-200 text-slate-700 font-bold flex items-center justify-center text-xs shadow-2xs border border-slate-200 cursor-pointer active:scale-95 transition-all"
                                    title="Tăng 5,000 đ"
                                  >
                                    +
                                  </button>
                                </div>
                              </td>
                              <td className="py-2.5 px-4 text-right">
                                <div className="flex items-center justify-end gap-1.5 flex-wrap">
                                  {modalPaymentTab === 'paid' ? (
                                    <button
                                      type="button"
                                      onClick={() => handleModalUnmarkPaid([task.order_id])}
                                      className="inline-flex items-center gap-1 text-xs font-semibold text-amber-700 bg-amber-50 hover:bg-amber-100 px-2 py-1 rounded-md border border-amber-200 transition-colors cursor-pointer"
                                      title="Hủy trạng thái thanh toán cho đơn này"
                                    >
                                      <RotateCcw className="h-3 w-3 text-amber-600" />
                                      <span>Hủy</span>
                                    </button>
                                  ) : (
                                    <button
                                      type="button"
                                      onClick={() => handleModalMarkPaid([task.order_id])}
                                      className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 bg-emerald-50 hover:bg-emerald-100 px-2 py-1 rounded-md border border-emerald-200 transition-colors cursor-pointer"
                                      title="Xác nhận thanh toán cho đơn này"
                                    >
                                      <CreditCard className="h-3 w-3 text-emerald-600" />
                                      <span>Trả</span>
                                    </button>
                                  )}

                                  <button
                                    type="button"
                                    onClick={() => setTimelineOrder({ id: task.order_id, code: task.external_order_id, name: task.product_name })}
                                    className="inline-flex items-center gap-1 text-xs font-bold text-slate-700 bg-slate-100 hover:bg-blue-50 hover:text-[#0052CC] px-2 py-1 rounded-md border border-slate-200 transition-colors cursor-pointer"
                                    title="Xem toàn bộ lịch sử Timeline chuyển trạng thái"
                                  >
                                    <History className="h-3.5 w-3.5 text-slate-500" />
                                    <span>Timeline</span>
                                  </button>

                                  <button
                                    type="button"
                                    onClick={() => openAddNoteModal('order', task.order_id, task.external_order_id)}
                                    className="inline-flex items-center gap-1 text-xs font-bold text-slate-700 bg-slate-100 hover:bg-amber-50 hover:text-amber-800 hover:border-amber-200 px-2 py-1 rounded-md border border-slate-200 transition-colors cursor-pointer"
                                    title="Thêm ghi chú cho đơn hàng này"
                                  >
                                    <Plus className="h-3 w-3 text-slate-500" />
                                    <span>Note</span>
                                  </button>

                                  <Link
                                    to={`/orders/${task.order_id}`}
                                    className="inline-flex items-center gap-1 text-xs font-semibold text-[#0052CC] hover:text-[#003D99] hover:bg-blue-50 px-2 py-1 rounded-md transition-colors"
                                    title="Xem trang chi tiết đơn hàng"
                                  >
                                    <span>Chi tiết</span>
                                    <ChevronRight className="h-3.5 w-3.5" />
                                  </Link>
                                </div>
                              </td>
                            </tr>
                          )
                        })
                      )}
                    </tbody>
                  </table>
                </div>

                {modalTotalCount > 50 && (
                  <Pagination
                    totalItems={modalTotalCount}
                    currentPage={modalPage}
                    pageSize={50}
                    onPageChange={setModalPage}
                  />
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  )
}
