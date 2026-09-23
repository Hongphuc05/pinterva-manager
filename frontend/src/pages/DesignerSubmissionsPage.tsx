import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  FolderGit2,
  Search,
  RefreshCw,
  ExternalLink,
  Edit3,
  CheckCircle2,
  Clock,
  Layers,
  FileCheck,
  User,
  AlertTriangle,
  X,
  History,
} from 'lucide-react'
import { Sidebar } from '../components/Sidebar'
import { useAuth } from '../auth/AuthContext'
import { usePlatform } from '../auth/PlatformContext'
import { sortUsersByRoleAndName } from '../utils/userSorting'
import { useToast } from '../context/ToastContext'
import { apiFetch } from '../api/client'
import { ImageModal } from '../components/ImageModal'

interface SubmittedVersion {
  id: string
  assignment_id: string
  version_marker: number
  drive_url: string
  submitted_at: string | null
  created_at: string
}

interface SubmissionItem {
  order_id: string
  external_order_id: string
  product_name: string | null
  thumbnail_url: string | null
  sku: string | null
  designer_id: string | null
  designer_name: string | null
  designer_username: string | null
  first_submitted_at: string | null
  latest_submitted_at: string | null
  first_drive_url: string | null
  latest_drive_url: string | null
  versions: SubmittedVersion[]
  current_note_outsource: string | null
  order_state: string
  printerval_status: string | null
  created_at: string
}

interface SubmissionsResponse {
  items: SubmissionItem[]
  total_items: number
  page: number
  page_size: number
  total_pages: number
  total_versions_count: number
  total_first_versions_count: number
}

interface UserItem {
  id: string
  username: string
  full_name: string | null
  role: string
}

export function DesignerSubmissionsPage() {
  const { user } = useAuth()
  const { activePlatform } = usePlatform()
  const { showToast } = useToast()

  const [mobileOpen, setMobileOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<SubmissionsResponse | null>(null)
  const [designers, setDesigners] = useState<UserItem[]>([])

  // Filters
  const [search, setSearch] = useState('')
  const [selectedDesignerId, setSelectedDesignerId] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [page, setPage] = useState(1)

  // Edit Link Modal state
  const [editModalItem, setEditModalItem] = useState<SubmissionItem | null>(null)
  const [selectedVersionId, setSelectedVersionId] = useState<string>('')
  const [editDriveUrl, setEditDriveUrl] = useState('')
  const [editReason, setEditReason] = useState('')
  const [savingOverride, setSavingOverride] = useState(false)

  // Version History Modal state
  const [historyModalItem, setHistoryModalItem] = useState<SubmissionItem | null>(null)

  // Product thumbnail preview state
  const [selectedImage, setSelectedImage] = useState<string | null>(null)

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (editModalItem && !savingOverride) setEditModalItem(null)
        else if (historyModalItem) setHistoryModalItem(null)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [editModalItem, savingOverride, historyModalItem])

  const fetchDesigners = useCallback(async () => {
    try {
      const res = await apiFetch<UserItem[]>('/orders/designer-submissions/designers')
      const filtered = res.filter((u) => u.role === 'designer' || u.role === 'designer-trello' || u.role === 'designer_trello')
      setDesigners(sortUsersByRoleAndName(filtered))
    } catch {
      // The submissions table remains usable even if the options request fails.
      setDesigners([])
    }
  }, [])

  const fetchSubmissions = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', page.toString())
      params.set('page_size', '30')

      if (search.trim()) params.set('search', search.trim())
      if (selectedDesignerId) params.set('designer_id', selectedDesignerId)
      if (dateFrom) params.set('date_from', new Date(dateFrom).toISOString())
      if (dateTo) params.set('date_to', new Date(dateTo + 'T23:59:59').toISOString())

      const res = await apiFetch<SubmissionsResponse>(`/orders/designer-submissions?${params.toString()}`)
      setData(res)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Không thể tải danh sách link nộp bài'
      showToast(msg, 'error')
    } finally {
      setLoading(false)
    }
  }, [page, search, selectedDesignerId, dateFrom, dateTo, showToast])

  useEffect(() => {
    fetchDesigners()
  }, [fetchDesigners])

  useEffect(() => {
    fetchSubmissions()
  }, [fetchSubmissions])

  const handleOpenEditModal = (item: SubmissionItem) => {
    setEditModalItem(item)
    // Default to the latest version or first version
    const latest = item.versions[item.versions.length - 1]
    if (latest) {
      setSelectedVersionId(latest.id)
      setEditDriveUrl(latest.drive_url)
    } else {
      setSelectedVersionId('')
      setEditDriveUrl(item.latest_drive_url || '')
    }
    setEditReason('')
  }

  const handleSaveOverride = async () => {
    if (!editModalItem) return
    if (!editDriveUrl.trim()) {
      showToast('Vui lòng nhập link Drive nộp bài', 'warning')
      return
    }

    setSavingOverride(true)
    try {
      const payload = {
        version_id: selectedVersionId || null,
        drive_url: editDriveUrl.trim(),
        reason: editReason.trim() || 'Admin cập nhật link thủ công',
      }
      const res = await apiFetch<{ message: string }>(
        `/orders/${editModalItem.order_id}/override-submission-link`,
        {
          method: 'POST',
          body: JSON.stringify(payload),
        }
      )
      showToast(res.message || 'Đã cập nhật link nộp bài thành công', 'success')
      setEditModalItem(null)
      fetchSubmissions()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Lỗi khi cập nhật link nộp bài'
      showToast(msg, 'error')
    } finally {
      setSavingOverride(false)
    }
  }

  const formatDate = (isoStr: string | null) => {
    if (!isoStr) return '---'
    try {
      const d = new Date(isoStr)
      return d.toLocaleString('vi-VN', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return isoStr
    }
  }

  const isDriveUrl = (url: string | null) => {
    if (!url) return false
    return url.includes('drive.google.com') || url.startsWith('http://') || url.startsWith('https://')
  }

  return (
    <div className="flex h-screen bg-slate-50 font-sans text-slate-800 antialiased">
      <ImageModal
        isOpen={!!selectedImage}
        onClose={() => setSelectedImage(null)}
        imageUrl={selectedImage}
        altText="Ảnh sản phẩm"
      />

      <Sidebar mobileOpen={mobileOpen} onMobileClose={() => setMobileOpen(false)} />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top Header */}
        <header className="flex h-16 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 shadow-sm">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-blue-600 p-2 text-white shadow-sm">
              <FolderGit2 className="h-5 w-5" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-slate-900 leading-tight">
                Kho Lưu Link Nộp Bài Designer
              </h1>
              <p className="text-xs text-slate-500 font-medium">
                Single Source of Truth cho toàn bộ link bài nộp v1, v2,... của Designer
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={() => fetchSubmissions()}
              disabled={loading}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
              Làm mới
            </button>
          </div>
        </header>

        {/* Main Content Area */}
        <main className="flex-1 overflow-y-auto p-6">
          {/* Summary Stat Cards */}
          <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Tổng Đơn Đã Nộp</p>
                <p className="mt-1 text-2xl font-black text-slate-900">{data?.total_items ?? 0}</p>
                <p className="mt-0.5 text-[11px] text-slate-400">Có dữ liệu link bài nộp</p>
              </div>
              <div className="rounded-xl bg-blue-50 p-3 text-blue-600">
                <FileCheck className="h-6 w-6" />
              </div>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Tổng Link Bài (Phiên Bản)</p>
                <p className="mt-1 text-2xl font-black text-slate-900">{data?.total_versions_count ?? 0}</p>
                <p className="mt-0.5 text-[11px] text-slate-400">Bao gồm các bản sửa đổi v2, v3...</p>
              </div>
              <div className="rounded-xl bg-purple-50 p-3 text-purple-600">
                <Layers className="h-6 w-6" />
              </div>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Bản Nộp Đầu (Bản v1)</p>
                <p className="mt-1 text-2xl font-black text-slate-900">{data?.total_first_versions_count ?? 0}</p>
                <p className="mt-0.5 text-[11px] text-emerald-600 font-medium">Kho Backup gốc an toàn</p>
              </div>
              <div className="rounded-xl bg-emerald-50 p-3 text-emerald-600">
                <CheckCircle2 className="h-6 w-6" />
              </div>
            </div>

            <div className="flex items-center justify-between rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div>
                <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Platform Hiện Tại</p>
                <p className="mt-1 text-base font-bold text-slate-800 truncate max-w-[150px]">
                  {activePlatform?.name || 'Tất cả Platform'}
                </p>
                <p className="mt-0.5 text-[11px] text-slate-400">Bộ lọc theo store active</p>
              </div>
              <div className="rounded-xl bg-amber-50 p-3 text-amber-600">
                <User className="h-6 w-6" />
              </div>
            </div>
          </div>

          {/* Filter Bar */}
          <div className="mb-6 rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="flex flex-wrap items-center gap-4">
              {/* Search */}
              <div className="relative flex-1 min-w-[240px]">
                <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                <input
                  type="text"
                  placeholder="Tìm mã đơn (DJ...), tên sản phẩm, link Drive..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && setPage(1)}
                  className="w-full rounded-lg border border-slate-300 bg-slate-50/50 pl-9 pr-3 py-2 text-xs font-medium text-slate-800 placeholder-slate-400 transition focus:border-blue-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              {/* Designer Selector */}
              <div className="min-w-[180px]">
                <select
                  value={selectedDesignerId}
                  onChange={(e) => {
                    setSelectedDesignerId(e.target.value)
                    setPage(1)
                  }}
                  className="w-full rounded-lg border border-slate-300 bg-slate-50/50 px-3 py-2 text-xs font-medium text-slate-800 transition focus:border-blue-500 focus:bg-white focus:outline-none"
                >
                  <option value="">Tất cả Designer</option>
                  {designers.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.full_name || d.username}
                    </option>
                  ))}
                </select>
              </div>

              {/* Date From */}
              <div className="flex items-center gap-2 text-xs font-medium text-slate-600">
                <span>Từ:</span>
                <input
                  type="date"
                  value={dateFrom}
                  onChange={(e) => {
                    setDateFrom(e.target.value)
                    setPage(1)
                  }}
                  className="rounded-lg border border-slate-300 bg-slate-50/50 px-2.5 py-1.5 text-xs text-slate-800 focus:border-blue-500 focus:outline-none"
                />
              </div>

              {/* Date To */}
              <div className="flex items-center gap-2 text-xs font-medium text-slate-600">
                <span>Đến:</span>
                <input
                  type="date"
                  value={dateTo}
                  onChange={(e) => {
                    setDateTo(e.target.value)
                    setPage(1)
                  }}
                  className="rounded-lg border border-slate-300 bg-slate-50/50 px-2.5 py-1.5 text-xs text-slate-800 focus:border-blue-500 focus:outline-none"
                />
              </div>

              {(search || selectedDesignerId || dateFrom || dateTo) && (
                <button
                  onClick={() => {
                    setSearch('')
                    setSelectedDesignerId('')
                    setDateFrom('')
                    setDateTo('')
                    setPage(1)
                  }}
                  className="rounded-lg px-3 py-1.5 text-xs font-semibold text-rose-600 hover:bg-rose-50 transition"
                >
                  Xóa bộ lọc
                </button>
              )}
            </div>
          </div>

          {/* Submissions Table */}
          <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-slate-200 bg-slate-100/70 text-slate-600 uppercase tracking-wider font-bold">
                    <th className="px-4 py-3">Mã Đơn / Sản Phẩm</th>
                    <th className="px-4 py-3">Designer</th>
                    <th className="px-4 py-3 bg-emerald-50/50 text-emerald-800">
                      Link Nộp Lần Đầu (Bản v1)
                    </th>
                    <th className="px-4 py-3 bg-blue-50/50 text-blue-800">
                      Link Mới Nhất & Lịch Sử
                    </th>
                    <th className="px-4 py-3">Note Outsource (Printerval)</th>
                    <th className="px-4 py-3 text-center">Thao Tác Admin</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {loading ? (
                    <tr>
                      <td colSpan={6} className="py-12 text-center text-slate-400">
                        <RefreshCw className="mx-auto h-6 w-6 animate-spin text-blue-500 mb-2" />
                        Đang tải danh sách kho bài nộp...
                      </td>
                    </tr>
                  ) : !data || data.items.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="py-12 text-center text-slate-500">
                        <FolderGit2 className="mx-auto h-8 w-8 text-slate-300 mb-2" />
                        Chưa tìm thấy bài nộp nào phù hợp
                      </td>
                    </tr>
                  ) : (
                    data.items.map((item) => {
                      const noteHasDrive = isDriveUrl(item.current_note_outsource)
                      return (
                        <tr key={item.order_id} className="hover:bg-slate-50/80 transition">
                          {/* Order Code & Product */}
                          <td className="px-4 py-3.5 align-top">
                            <div className="flex items-start gap-3">
                              {item.thumbnail_url ? (
                                <button
                                  type="button"
                                  onClick={() => setSelectedImage(item.thumbnail_url)}
                                  className="h-10 w-10 shrink-0 cursor-zoom-in rounded-md border-0 bg-transparent p-0 transition hover:ring-2 hover:ring-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                                  title="Xem ảnh sản phẩm"
                                  aria-label={`Xem ảnh sản phẩm ${item.external_order_id}`}
                                >
                                  <img
                                    src={item.thumbnail_url}
                                    alt=""
                                    className="h-full w-full rounded-md border border-slate-200 object-cover"
                                  />
                                </button>
                              ) : (
                                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-slate-200 bg-slate-100 text-slate-400 font-bold text-xs">
                                  N/A
                                </div>
                              )}
                              <div>
                                <Link
                                  to={`/orders/${item.order_id}`}
                                  className="font-bold text-blue-600 hover:underline text-sm inline-flex items-center gap-1"
                                >
                                  {item.external_order_id}
                                  <ExternalLink className="h-3 w-3" />
                                </Link>
                                <p className="font-medium text-slate-700 line-clamp-1 mt-0.5">
                                  {item.product_name || 'Không có tên sản phẩm'}
                                </p>
                                <span className="inline-block rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono text-slate-500 mt-1">
                                  State: {item.order_state}
                                </span>
                              </div>
                            </div>
                          </td>

                          {/* Designer */}
                          <td className="px-4 py-3.5 align-top">
                            <div className="font-semibold text-slate-800">
                              {item.designer_name || 'Chưa phân công'}
                            </div>
                            {item.designer_username && (
                              <span className="text-[11px] text-slate-400">@{item.designer_username}</span>
                            )}
                          </td>

                          {/* First Submission (v1) */}
                          <td className="px-4 py-3.5 align-top bg-emerald-50/20">
                            {item.first_drive_url ? (
                              <div>
                                <a
                                  href={item.first_drive_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1.5 font-bold text-emerald-700 hover:text-emerald-900 hover:underline max-w-[200px] truncate"
                                  title={item.first_drive_url}
                                >
                                  <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                                  <span className="truncate">{item.first_drive_url}</span>
                                </a>
                                <div className="mt-1 flex items-center gap-1 text-[10px] font-medium text-emerald-600">
                                  <Clock className="h-3 w-3" />
                                  <span>{formatDate(item.first_submitted_at)}</span>
                                </div>
                              </div>
                            ) : (
                              <span className="text-slate-400 italic">Chưa có bài nộp v1</span>
                            )}
                          </td>

                          {/* Latest Submission & History */}
                          <td className="px-4 py-3.5 align-top bg-blue-50/20">
                            {item.latest_drive_url ? (
                              <div>
                                <div className="flex items-center gap-2">
                                  <a
                                    href={item.latest_drive_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="inline-flex items-center gap-1.5 font-bold text-blue-700 hover:text-blue-900 hover:underline max-w-[180px] truncate"
                                    title={item.latest_drive_url}
                                  >
                                    <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                                    <span className="truncate">{item.latest_drive_url}</span>
                                  </a>
                                  <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-bold text-blue-800 shrink-0">
                                    v{item.versions.length}
                                  </span>
                                </div>
                                <div className="mt-1 flex items-center gap-2">
                                  <span className="text-[10px] font-medium text-slate-500">
                                    {formatDate(item.latest_submitted_at)}
                                  </span>
                                  {item.versions.length > 1 && (
                                    <button
                                      onClick={() => setHistoryModalItem(item)}
                                      className="inline-flex items-center gap-1 text-[10px] font-bold text-purple-600 hover:underline"
                                    >
                                      <History className="h-3 w-3" />
                                      Xem {item.versions.length} phiên bản
                                    </button>
                                  )}
                                </div>
                              </div>
                            ) : (
                              <span className="text-slate-400 italic">Chưa có bài nộp</span>
                            )}
                          </td>

                          {/* Note Outsource from Printerval */}
                          <td className="px-4 py-3.5 align-top">
                            {item.current_note_outsource ? (
                              <div className="max-w-[220px]">
                                {noteHasDrive ? (
                                  <span className="font-mono text-[11px] text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200 block truncate">
                                    {item.current_note_outsource}
                                  </span>
                                ) : (
                                  <div>
                                    <span className="text-[11px] text-amber-700 font-medium bg-amber-50 px-1.5 py-0.5 rounded border border-amber-200 block line-clamp-2">
                                      {item.current_note_outsource}
                                    </span>
                                    <span className="mt-1 inline-flex items-center gap-1 text-[10px] text-amber-600 font-medium">
                                      <AlertTriangle className="h-3 w-3 shrink-0" />
                                      Printerval đã đè nội dung phản hồi
                                    </span>
                                  </div>
                                )}
                              </div>
                            ) : (
                              <span className="text-slate-400 text-[11px] italic">Trống</span>
                            )}
                          </td>

                          {/* Admin Edit Action */}
                          <td className="px-4 py-3.5 align-top text-center">
                            {user?.role === 'admin' ? (
                              <button
                                onClick={() => handleOpenEditModal(item)}
                                className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:border-blue-500 hover:bg-blue-50 hover:text-blue-700"
                              >
                                <Edit3 className="h-3.5 w-3.5 text-blue-600" />
                                Sửa Link
                              </button>
                            ) : (
                              <span className="text-slate-400 text-[11px] italic">Chỉ xem</span>
                            )}
                          </td>
                        </tr>
                      )
                    })
                  )}
                </tbody>
              </table>
            </div>

            {/* Pagination Controls */}
            {data && data.total_pages > 1 && (
              <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50 px-4 py-3">
                <p className="text-xs text-slate-500">
                  Hiển thị <span className="font-bold text-slate-800">{data.items.length}</span> /{' '}
                  <span className="font-bold text-slate-800">{data.total_items}</span> đơn hàng
                </p>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPage((p) => Math.max(1, p - 1))}
                    disabled={page === 1}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-100 disabled:opacity-40"
                  >
                    Trang trước
                  </button>
                  <span className="text-xs font-bold text-slate-700">
                    Trang {page} / {data.total_pages}
                  </span>
                  <button
                    onClick={() => setPage((p) => Math.min(data.total_pages, p + 1))}
                    disabled={page === data.total_pages}
                    className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-100 disabled:opacity-40"
                  >
                    Trang sau
                  </button>
                </div>
              </div>
            )}
          </div>
        </main>
      </div>

      {/* Admin Override Link Modal */}
      {editModalItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl transition-all">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4">
              <div className="flex items-center gap-2">
                <Edit3 className="h-5 w-5 text-blue-600" />
                <h3 className="text-base font-bold text-slate-900">
                  Cập Nhật / Sửa Link Nộp Bài (Admin Override)
                </h3>
              </div>
              <button
                onClick={() => setEditModalItem(null)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="mt-4 space-y-4 text-xs">
              <div className="rounded-lg bg-slate-50 p-3 border border-slate-200">
                <p className="font-bold text-slate-800 text-sm">{editModalItem.external_order_id}</p>
                <p className="text-slate-600 mt-0.5">{editModalItem.product_name || 'Không có tên sản phẩm'}</p>
                <p className="text-slate-500 mt-1">
                  Designer:{' '}
                  <span className="font-semibold text-slate-700">
                    {editModalItem.designer_name || 'Chưa gán'}
                  </span>
                </p>
              </div>

              {/* Version Selector */}
              {editModalItem.versions.length > 0 && (
                <div>
                  <label className="block font-bold text-slate-700 mb-1">
                    Chọn phiên bản cần cập nhật:
                  </label>
                  <select
                    value={selectedVersionId}
                    onChange={(e) => {
                      const vid = e.target.value
                      setSelectedVersionId(vid)
                      const target = editModalItem.versions.find((v) => v.id === vid)
                      if (target) setEditDriveUrl(target.drive_url)
                    }}
                    className="w-full rounded-lg border border-slate-300 p-2 text-xs font-medium focus:border-blue-500 focus:outline-none"
                  >
                    {editModalItem.versions.map((v) => (
                      <option key={v.id} value={v.id}>
                        Bản v{v.version_marker} ({formatDate(v.submitted_at || v.created_at)}) - {v.drive_url}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Drive Link Input */}
              <div>
                <label className="block font-bold text-slate-700 mb-1">
                  Link Google Drive bài nộp mới: <span className="text-rose-500">*</span>
                </label>
                <input
                  type="text"
                  placeholder="https://drive.google.com/file/d/..."
                  value={editDriveUrl}
                  onChange={(e) => setEditDriveUrl(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 p-2.5 text-xs font-mono text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              {/* Reason */}
              <div>
                <label className="block font-bold text-slate-700 mb-1">Ghi chú / Lý do chỉnh sửa:</label>
                <input
                  type="text"
                  placeholder="Ví dụ: Link cũ bị lỗi hỏng file, Admin hỗ trợ sửa lại..."
                  value={editReason}
                  onChange={(e) => setEditReason(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 p-2 text-xs text-slate-800 focus:border-blue-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="mt-6 flex items-center justify-end gap-3 border-t border-slate-100 pt-4">
              <button
                onClick={() => setEditModalItem(null)}
                className="rounded-lg border border-slate-300 px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
              >
                Hủy
              </button>
              <button
                onClick={handleSaveOverride}
                disabled={savingOverride}
                className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-blue-700 transition disabled:opacity-50"
              >
                {savingOverride && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
                Lưu Thay Thế Link
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Version History Modal */}
      {historyModalItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4 backdrop-blur-sm">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-100 pb-4">
              <div className="flex items-center gap-2">
                <History className="h-5 w-5 text-purple-600" />
                <h3 className="text-base font-bold text-slate-900">
                  Lịch Sử Các Phiên Bản Bài Nộp ({historyModalItem.external_order_id})
                </h3>
              </div>
              <button
                onClick={() => setHistoryModalItem(null)}
                className="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="mt-4 space-y-3 max-h-[60vh] overflow-y-auto pr-1">
              {historyModalItem.versions.map((ver) => (
                <div
                  key={ver.id}
                  className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 text-xs space-y-1.5"
                >
                  <div className="flex items-center justify-between">
                    <span className="rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-extrabold text-purple-800">
                      Phiên bản v{ver.version_marker}
                    </span>
                    <span className="text-[11px] text-slate-500 font-medium">
                      {formatDate(ver.submitted_at || ver.created_at)}
                    </span>
                  </div>

                  <a
                    href={ver.drive_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 font-bold text-blue-600 hover:underline break-all"
                  >
                    <ExternalLink className="h-3.5 w-3.5 shrink-0" />
                    {ver.drive_url}
                  </a>
                </div>
              ))}
            </div>

            <div className="mt-6 flex justify-end border-t border-slate-100 pt-4">
              <button
                onClick={() => setHistoryModalItem(null)}
                className="rounded-lg bg-slate-800 px-4 py-2 text-xs font-bold text-white hover:bg-slate-900"
              >
                Đóng
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
