import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiFetch, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { ImageModal } from '../components/ImageModal'
import { Pagination, paginate } from '../components/Pagination'
import { getStatusInfo } from '../utils/statusTranslation'
import { 
  CheckSquare, 
  Clock, 
  AlertCircle, 
  Package,
  ChevronRight,
  FolderArchive
} from 'lucide-react'

type ResultVersion = {
  id: string
  drive_url: string
  version_marker: number
  submitted_at: string | null
  qc_feedback: string | null
}

type Task = {
  assignment_id: string
  sub_status: string | null
  order: {
    id: string
    external_order_id: string
    state: string
    product_name: string | null
    thumbnail_url: string | null
    sku: string | null
    product_category: string | null
    product_variants: { name: string; value: string }[] | null
    product_skus: { sku?: string | null }[] | null
    deadline_at_ext: string | null
    note_outsource: string | null
    order_note: string
    custom_config: Record<string, unknown> | null
    sku_image_url: string | null
    external_order_url: string | null
    source_files: { name: string; url: string }[] | null
    source_download_all_url: string | null
    design_tool_url: string | null
  }
  result_versions: ResultVersion[]
}

const subStatusLabels: Record<string, string> = { doing: 'Đang làm', fixing: 'Đang sửa', done: 'Đã xong' }

export function MyTasksPage() {
  const { user } = useAuth()
  const [tasks, setTasks] = useState<Task[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedImage, setSelectedImage] = useState<string | null>(null)
  const [currentPage, setCurrentPage] = useState(1)

  async function loadTasks() {
    setLoading(true)
    try {
      const data = await apiFetch<{ tasks: Task[] }>('/my-tasks')
      setTasks(data.tasks)
      setError(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không tải được danh sách task.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTasks()
  }, [])

  useEffect(() => {
    setCurrentPage(1)
  }, [tasks.length])

  if (user?.role !== 'designer') {
    return (
      <DashboardLayout>
        <div className="p-8 text-center bg-white rounded-xl border border-slate-200 shadow-xs text-slate-500">
          <AlertCircle className="h-10 w-10 mx-auto text-amber-500 mb-2" />
          <h2 className="text-base font-bold text-slate-800">Truy Cập Hạn Chế</h2>
          <p className="text-xs text-slate-500 mt-1">Trang này dành riêng cho tài khoản role Designer.</p>
        </div>
      </DashboardLayout>
    )
  }

  return (
    <DashboardLayout>
      {/* Image Zoom Modal */}
      <ImageModal
        isOpen={!!selectedImage}
        onClose={() => setSelectedImage(null)}
        imageUrl={selectedImage}
        hideExternalLink={true}
      />

      {/* Header Info */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
        <div>
          <h2 className="text-base font-bold text-slate-800 flex items-center gap-2">
            <CheckSquare className="h-5 w-5 text-[#0052CC]" />
            <span>Nhiệm Vụ Thiết Kế Của Tôi (My Tasks)</span>
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Danh sách các đơn hàng được gán cho bạn. Click vào đơn hàng để xem chi tiết, tải file và nộp bài.
          </p>
        </div>
        <span className="font-mono text-xs font-bold px-3 py-1 bg-blue-50 text-[#0052CC] border border-blue-200 rounded-full">
          {tasks.length} Task Active
        </span>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs font-semibold flex items-center gap-2">
          <AlertCircle className="h-4 w-4 shrink-0 text-red-600" />
          <span>{error}</span>
        </div>
      )}

      {/* Tasks List */}
      {loading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((n) => (
            <div key={n} className="rounded-xl border border-slate-200 bg-white p-5 h-28 animate-pulse space-y-3">
              <div className="h-5 bg-slate-200 rounded-md w-1/3"></div>
              <div className="h-4 bg-slate-100 rounded-md w-2/3"></div>
            </div>
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center text-slate-400">
          <CheckSquare className="h-12 w-12 mx-auto mb-3 opacity-25 text-slate-500" />
          <h3 className="text-sm font-semibold text-slate-700">Chưa có task nào được gán</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">Vào trang "Tất Cả Đơn Hàng" để xem danh sách chung hoặc chờ Admin gán công việc cho bạn.</p>
        </div>
      ) : (
        <>
          <div className="space-y-4">
            {paginate(tasks, currentPage).map((task) => {
            const statusInfo = getStatusInfo(task.order.state)
            const sourceCount = task.order.source_files?.length ?? 0

            return (
              <article
                key={task.assignment_id}
                className="rounded-xl border border-slate-200 bg-white p-5 shadow-xs hover:shadow-md transition-all flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
              >
                <div className="flex items-start gap-4 flex-1 min-w-0">
                  {/* Product Thumbnail */}
                  {task.order.thumbnail_url ? (
                    <img
                      src={resolveAssetUrl(task.order.thumbnail_url)}
                      alt={task.order.product_name || 'Ảnh sản phẩm'}
                      title="Click để phóng to ảnh"
                      onClick={() => setSelectedImage(resolveAssetUrl(task.order.thumbnail_url))}
                      className="h-16 w-16 rounded-xl object-cover border border-slate-200 shrink-0 cursor-pointer hover:scale-105 transition-transform"
                    />
                  ) : (
                    <div className="h-16 w-16 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                      <Package className="h-7 w-7" />
                    </div>
                  )}

                  {/* Order Info */}
                  <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Link
                        to={`/orders/${task.order.id}`}
                        className="text-base font-bold text-[#0052CC] hover:underline"
                        title={task.order.product_name ?? 'Đơn thiết kế 2D'}
                      >
                        {task.order.product_name ?? 'Đơn thiết kế 2D'}
                      </Link>

                      {task.order.sku_image_url && (
                        <button
                          type="button"
                          onClick={() => setSelectedImage(task.order.sku_image_url)}
                          className="text-xs font-bold text-[#0052CC] hover:underline flex items-center gap-0.5 px-2 py-0.5 rounded bg-blue-50 border border-blue-100 cursor-pointer"
                          title="Xem ảnh mẫu"
                        >
                          <span>Xem ảnh</span>
                        </button>
                      )}

                      <span
                        title={statusInfo.description}
                        className={`text-xs font-semibold px-2.5 py-0.5 rounded-md border ${statusInfo.badgeClass}`}
                      >
                        {statusInfo.label}
                      </span>

                      {task.sub_status && subStatusLabels[task.sub_status] && (
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-md bg-purple-50 text-purple-700 border border-purple-200">
                          {subStatusLabels[task.sub_status]}
                        </span>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 font-mono pt-0.5">
                      {task.order.deadline_at_ext && (
                        <span className="flex items-center gap-1">
                          <Clock className="h-3.5 w-3.5 text-amber-600" />
                          <span>Deadline: {new Date(task.order.deadline_at_ext).toLocaleString('vi-VN')}</span>
                        </span>
                      )}

                      {sourceCount > 0 && (
                        <span className="flex items-center gap-1 text-slate-600 font-semibold bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
                          <FolderArchive className="h-3 w-3 text-slate-500" />
                          <span>{sourceCount} file source</span>
                        </span>
                      )}

                      {task.order.product_skus && task.order.product_skus.length > 1 && (
                        <span className="inline-flex items-center gap-1 text-slate-600 font-semibold bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
                          <Package className="h-3 w-3 text-slate-500" />
                          <span>{task.order.product_skus.length} mẫu hàng</span>
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Right Action Button */}
                <div className="shrink-0 w-full sm:w-auto text-right border-t sm:border-t-0 pt-3 sm:pt-0 border-slate-100">
                  <Link
                    to={`/orders/${task.order.id}`}
                    className="inline-flex items-center justify-center gap-1 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl transition-all shadow-2xs hover:shadow-xs w-full sm:w-auto"
                  >
                    <span>Xem Chi Tiết & Nộp Bài</span>
                    <ChevronRight className="h-4 w-4" />
                  </Link>
                </div>
              </article>
            )
            })}
          </div>

          <Pagination
            totalItems={tasks.length}
            currentPage={currentPage}
            onPageChange={setCurrentPage}
          />
        </>
      )}
    </DashboardLayout>
  )
}
