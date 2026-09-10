import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiFetch, ApiError, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { Pagination } from '../components/Pagination'
import { ImageModal } from '../components/ImageModal'
import { getStatusInfo } from '../utils/statusTranslation'
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
  FileText
} from 'lucide-react'

type DesignerSummary = {
  designer_id: string | null
  designer_name: string
  username: string | null
  total_tasks: number
  in_review_tasks: number
  in_fix_tasks: number
  done_tasks: number
  first_submission_at: string | null
  latest_submission_at: string | null
}

type CreditedTask = {
  order_id: string
  external_order_id: string
  product_name: string | null
  thumbnail_url: string | null
  designer_id: string | null
  designer_name: string
  current_state: string
  printerval_status: string | null
  drive_link: string | null
  first_submitted_at: string
  latest_submitted_at: string
  submission_count: number
  order_created_at: string
}

type FinanceStatsResponse = {
  total_credited_tasks: number
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

export function FinancePage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const navigate = useNavigate()

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [data, setData] = useState<FinanceStatsResponse | null>(null)

  // Filters
  const [selectedDesigner, setSelectedDesigner] = useState<string>('')
  const [searchQuery, setSearchQuery] = useState('')
  const [stateFilter, setStateFilter] = useState('')
  const [currentPage, setCurrentPage] = useState(1)

  // Image modal
  const [selectedImage, setSelectedImage] = useState<string | null>(null)

  async function loadData() {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.set('page', currentPage.toString())
      params.set('page_size', '50')
      if (selectedDesigner) params.set('designer_id', selectedDesigner)
      if (searchQuery.trim()) params.set('search', searchQuery.trim())
      if (stateFilter) params.set('state', stateFilter)

      const res = await apiFetch<FinanceStatsResponse>(`/finance/stats?${params.toString()}`)
      setData(res)
      setError(null)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Không tải được dữ liệu tài chính.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadData()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage, selectedDesigner, stateFilter])

  // Search debounce
  useEffect(() => {
    const timer = setTimeout(() => {
      setCurrentPage(1)
      loadData()
    }, 300)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQuery])

  return (
    <DashboardLayout>
      {/* Image Zoom Modal */}
      <ImageModal
        isOpen={!!selectedImage}
        onClose={() => setSelectedImage(null)}
        imageUrl={selectedImage}
      />

      {/* Header Banner */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h2 className="text-base font-bold text-slate-800 flex items-center gap-2">
            <Coins className="h-5 w-5 text-[#0052CC]" />
            <span>{isAdmin ? 'Quản Lý Tài Chính & Ghi Nhận Công Designer' : 'Bảng Ghi Nhận Công Lao Của Tôi'}</span>
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            {isAdmin
              ? 'Hệ thống tự động ghi nhận 1 công cho Designer khi nộp bài Review lần đầu tiên (không tính trùng lặp dù nộp nhiều lần hoặc sửa bài).'
              : 'Theo dõi chi tiết tất cả các đơn bạn đã nộp bài thiết kế được hệ thống ghi nhận tính công.'}
          </p>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-800 text-xs font-medium">
          {error}
        </div>
      )}

      {/* Global Summary KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4">
        <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Tổng Đơn Tính Công</p>
            <h3 className="text-2xl font-bold font-mono text-[#0052CC] mt-1">
              {data?.total_credited_tasks ?? 0}
            </h3>
            <p className="text-[11px] text-slate-400 mt-0.5">Đã nộp bài QC</p>
          </div>
          <div className="p-3 bg-blue-50 text-[#0052CC] rounded-xl">
            <CheckCircle2 className="h-6 w-6" />
          </div>
        </div>

        {isAdmin ? (
          <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Designer Hoạt Động</p>
              <h3 className="text-2xl font-bold font-mono text-purple-600 mt-1">
                {data?.total_designers ?? 0}
              </h3>
              <p className="text-[11px] text-slate-400 mt-0.5">Có đơn nộp bài</p>
            </div>
            <div className="p-3 bg-purple-50 text-purple-600 rounded-xl">
              <Users className="h-6 w-6" />
            </div>
          </div>
        ) : (
          <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Đã Hoàn Thành (Done)</p>
              <h3 className="text-2xl font-bold font-mono text-emerald-600 mt-1">
                {data?.total_done_tasks ?? 0}
              </h3>
              <p className="text-[11px] text-slate-400 mt-0.5">Duyệt hoàn tất</p>
            </div>
            <div className="p-3 bg-emerald-50 text-emerald-600 rounded-xl">
              <CheckCircle2 className="h-6 w-6" />
            </div>
          </div>
        )}

        <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Đang Chờ Duyệt (Review)</p>
            <h3 className="text-2xl font-bold font-mono text-purple-600 mt-1">
              {data?.total_in_review_tasks ?? 0}
            </h3>
            <p className="text-[11px] text-slate-400 mt-0.5">Chờ Admin / QC</p>
          </div>
          <div className="p-3 bg-purple-50 text-purple-600 rounded-xl">
            <Clock className="h-6 w-6" />
          </div>
        </div>

        <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
          <div>
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Yêu Cầu Sửa (Fix)</p>
            <h3 className="text-2xl font-bold font-mono text-orange-600 mt-1">
              {data?.total_in_fix_tasks ?? 0}
            </h3>
            <p className="text-[11px] text-slate-400 mt-0.5">Vẫn tính công đã nộp</p>
          </div>
          <div className="p-3 bg-orange-50 text-orange-600 rounded-xl">
            <AlertTriangle className="h-6 w-6" />
          </div>
        </div>
      </div>

      {/* Admin Designer Summary Table */}
      {isAdmin && data?.designers_summary && data.designers_summary.length > 0 && (
        <div className="rounded-xl border border-[hsl(var(--border))] bg-white shadow-xs overflow-hidden">
          <div className="px-5 py-3.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-2">
              <Users className="h-4 w-4 text-[#0052CC]" />
              <span>Bảng Tổng Hợp Công Theo Từng Designer ({data.designers_summary.length})</span>
            </h3>
            {selectedDesigner && (
              <button
                onClick={() => {
                  setSelectedDesigner('')
                  setCurrentPage(1)
                }}
                className="text-xs text-[#0052CC] hover:underline font-semibold cursor-pointer"
              >
                Hiển thị tất cả DES
              </button>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-50/50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500">
                  <th className="py-3 px-4">Designer</th>
                  <th className="py-3 px-4 text-center">Tổng Đơn Tính Công</th>
                  <th className="py-3 px-4 text-center">Đang Chờ Review</th>
                  <th className="py-3 px-4 text-center">Yêu Cầu Sửa (Fix)</th>
                  <th className="py-3 px-4 text-center">Đã Hoàn Thành</th>
                  <th className="py-3 px-4">Lần Nộp Đầu Tiên</th>
                  <th className="py-3 px-4">Lần Nộp Gần Nhất</th>
                  <th className="py-3 px-4 text-right">Thao Tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.designers_summary.map((des) => {
                  const isFiltered =
                    selectedDesigner &&
                    (selectedDesigner === des.designer_id || selectedDesigner === des.designer_name)

                  return (
                    <tr
                      key={des.designer_name}
                      className={`transition-colors hover:bg-blue-50/40 ${isFiltered ? 'bg-blue-50/80 font-medium' : ''}`}
                    >
                      <td className="py-3 px-4 font-semibold text-slate-800">
                        <div className="flex items-center gap-2">
                          <div className="w-7 h-7 rounded-full bg-blue-100 text-[#0052CC] font-bold flex items-center justify-center text-xs">
                            {des.designer_name.charAt(0).toUpperCase()}
                          </div>
                          <div>
                            <p className="font-semibold text-slate-800">{des.designer_name}</p>
                            {des.username && <p className="text-[10px] text-slate-400 font-normal">@{des.username}</p>}
                          </div>
                        </div>
                      </td>
                      <td className="py-3 px-4 text-center">
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-mono font-bold bg-blue-50 text-[#0052CC] border border-blue-200">
                          {des.total_tasks} đơn
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
                      <td className="py-3 px-4 text-slate-500 font-mono text-[11px]">
                        {des.first_submission_at ? new Date(des.first_submission_at).toLocaleString('vi-VN') : '—'}
                      </td>
                      <td className="py-3 px-4 text-slate-500 font-mono text-[11px]">
                        {des.latest_submission_at ? new Date(des.latest_submission_at).toLocaleString('vi-VN') : '—'}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedDesigner(des.designer_id || des.designer_name)
                            setCurrentPage(1)
                          }}
                          className={`px-2.5 py-1 text-xs font-semibold rounded-lg border transition-all cursor-pointer ${
                            isFiltered
                              ? 'bg-[#0052CC] text-white border-[#0052CC]'
                              : 'bg-slate-50 hover:bg-blue-50 text-[#0052CC] border-slate-200 hover:border-blue-200'
                          }`}
                        >
                          {isFiltered ? 'Đang lọc' : 'Xem đơn'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Detailed Credited Task List Section */}
      <div className="space-y-3">
        {/* Search & Filter Bar */}
        <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-4 shadow-xs space-y-3">
          <div className="flex flex-col md:flex-row items-center justify-between gap-4 flex-wrap">
            <div className="relative w-full md:w-72">
              <Search className="h-4 w-4 absolute left-3.5 top-3 text-slate-400" />
              <input
                type="text"
                placeholder="Tìm mã đơn, tên sản phẩm..."
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
                    }}
                  >
                    <option value="">Tất cả Designer</option>
                    {data?.designers_summary.map((d) => (
                      <option key={d.designer_name} value={d.designer_id || d.designer_name}>
                        {d.designer_name} ({d.total_tasks} đơn)
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
                  }}
                >
                  <option value="">Tất cả Trạng Thái</option>
                  <option value="REVIEW">Chờ Duyệt (Review)</option>
                  <option value="FIX">Yêu Cầu Sửa (Fix)</option>
                  <option value="DONE">Hoàn Thành (Done)</option>
                </select>
              </div>

              {(selectedDesigner || stateFilter || searchQuery) && (
                <button
                  onClick={() => {
                    setSelectedDesigner('')
                    setStateFilter('')
                    setSearchQuery('')
                    setCurrentPage(1)
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

        {/* Dense Table of Credited Tasks */}
        <div className="rounded-xl border border-[hsl(var(--border))] bg-white shadow-xs overflow-hidden">
          <div className="px-5 py-3.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
            <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider flex items-center gap-2">
              <FileText className="h-4 w-4 text-[#0052CC]" />
              <span>Danh Sách Đơn Ghi Nhận Tính Công ({data?.total_tasks_count ?? 0})</span>
            </h3>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-slate-50/50 border-b border-slate-200 text-[11px] font-semibold uppercase text-slate-500">
                  <th className="py-3 px-4 w-14 text-center">Ảnh</th>
                  <th className="py-3 px-4">Mã Đơn / Tên Sản Phẩm</th>
                  {isAdmin && <th className="py-3 px-4">Designer</th>}
                  <th className="py-3 px-4">Trạng Thái Hiện Tại</th>
                  <th className="py-3 px-4">Lần Đầu Nộp Bài</th>
                  <th className="py-3 px-4 text-center">Số Lần Nộp</th>
                  <th className="py-3 px-4">Link Bài Nộp</th>
                  <th className="py-3 px-4 text-right">Thao Tác</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {loading ? (
                  <tr>
                    <td colSpan={isAdmin ? 8 : 7} className="py-12 text-center text-slate-400">
                      <Loader2 className="h-8 w-8 mx-auto mb-2 animate-spin opacity-50" />
                      <p className="font-medium text-sm text-slate-500">Đang tải dữ liệu ghi nhận công…</p>
                    </td>
                  </tr>
                ) : !data?.tasks || data.tasks.length === 0 ? (
                  <tr>
                    <td colSpan={isAdmin ? 8 : 7} className="py-12 text-center text-slate-400">
                      <Package className="h-10 w-10 mx-auto mb-2 opacity-30" />
                      <p className="font-medium text-sm text-slate-500">Chưa có đơn nào được ghi nhận nộp bài</p>
                      <p className="text-xs text-slate-400 mt-1">Khi Designer bấm nộp bài Review, đơn sẽ tự động xuất hiện tại đây.</p>
                    </td>
                  </tr>
                ) : (
                  data.tasks.map((task) => {
                    const statusInfo = getStatusInfo(task.current_state)

                    return (
                      <tr
                        key={task.order_id}
                        onClick={() => navigate(`/orders/${task.order_id}`)}
                        className="transition-colors hover:bg-blue-50/60 cursor-pointer"
                        title="Click để mở chi tiết đơn hàng"
                      >
                        {/* Thumbnail */}
                        <td className="py-2.5 px-4 text-center" onClick={(e) => e.stopPropagation()}>
                          {task.thumbnail_url ? (
                            <img
                              src={resolveAssetUrl(task.thumbnail_url)}
                              alt={task.external_order_id}
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
                          <Link
                            to={`/orders/${task.order_id}`}
                            onClick={(e) => e.stopPropagation()}
                            className="font-mono font-bold text-[#0052CC] hover:underline"
                          >
                            {task.external_order_id}
                          </Link>
                          {task.product_name && (
                            <p className="text-[11px] text-slate-600 line-clamp-1 mt-0.5" title={task.product_name}>
                              {task.product_name}
                            </p>
                          )}
                        </td>

                        {/* Designer */}
                        {isAdmin && (
                          <td className="py-2.5 px-4 font-semibold text-slate-700">
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 border border-slate-200 text-xs">
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

                        {/* First Submitted At */}
                        <td className="py-2.5 px-4 font-mono text-slate-600 text-[11px]">
                          {new Date(task.first_submitted_at).toLocaleString('vi-VN')}
                        </td>

                        {/* Submission Count */}
                        <td className="py-2.5 px-4 text-center">
                          <span className="font-mono font-semibold px-2 py-0.5 rounded bg-slate-100 text-slate-700">
                            {task.submission_count} lần
                          </span>
                        </td>

                        {/* Drive / Result Link */}
                        <td className="py-2.5 px-4" onClick={(e) => e.stopPropagation()}>
                          {task.drive_link ? (
                            <a
                              href={task.drive_link}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-[11px] font-bold text-[#0052CC] hover:underline bg-blue-50 px-2 py-1 rounded border border-blue-200"
                            >
                              <span>Link Thiết Kế</span>
                              <ExternalLink className="h-3 w-3" />
                            </a>
                          ) : (
                            <span className="text-slate-400 italic text-[11px]">Chưa đính kèm link</span>
                          )}
                        </td>

                        {/* Actions */}
                        <td className="py-2.5 px-4 text-right" onClick={(e) => e.stopPropagation()}>
                          <Link
                            to={`/orders/${task.order_id}`}
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
    </DashboardLayout>
  )
}
