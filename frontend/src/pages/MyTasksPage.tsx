import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiFetch, resolveAssetUrl } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { ImageModal } from '../components/ImageModal'
import { Pagination, paginate } from '../components/Pagination'
import { CopyableProductName } from '../components/CopyableProductName'
import { getStatusInfo } from '../utils/statusTranslation'
import { ProductQuickViewModal } from '../components/ProductQuickViewModal'
import { 
  CheckSquare, 
  Clock, 
  AlertCircle, 
  Package,
  ChevronRight,
  FolderArchive,
  Flag,
  Check
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
    version: number
    external_order_id: string
    state: string
    product_name: string | null
    thumbnail_url: string | null
    sku: string | null
    product_category: string | null
    product_variants: { name: string; value: string }[] | null
    product_skus: { sku?: string | null }[] | null
    deadline_tacahu: string | null
    updated_at?: string | null
    processing_lock_owned_by_me?: boolean
    processing_lock_expires_at?: string | null
    note_outsource: string | null
    fix_return_count?: number
    designer_note: string
    template_missing: boolean
    custom_config: Record<string, unknown> | null
    sku_image_url: string | null
    external_order_url: string | null
    source_files: { name: string; url: string }[] | null
    source_download_all_url: string | null
    product_image_urls?: string[] | null
    design_tool_url: string | null
  }
  result_versions: ResultVersion[]
}

const subStatusLabels: Record<string, string> = { doing: 'Đang làm', fixing: 'Đang sửa', done: 'Đã xong' }

export function MyTasksPage() {
  const { user } = useAuth()
  const usesOrderConcurrency = user?.role === 'designer-trello'
  const [tasks, setTasks] = useState<Task[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [selectedImage, setSelectedImage] = useState<string | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [flaggingAssignmentId, setFlaggingAssignmentId] = useState<string | null>(null)
  const [startingAssignmentId, setStartingAssignmentId] = useState<string | null>(null)
  const [quickViewOrderId, setQuickViewOrderId] = useState<string | null>(null)

  const pendingTemplateTasks = tasks.filter((task) => task.order.template_missing)
  const activeTasks = tasks.filter((task) => !task.order.template_missing)

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
    const handleOrdersUpdated = () => { void loadTasks() }
    window.addEventListener('orders-updated', handleOrdersUpdated)
    return () => window.removeEventListener('orders-updated', handleOrdersUpdated)
  }, [])

  useEffect(() => {
    setCurrentPage(1)
  }, [tasks.length])

  async function flagMissingTemplate(task: Task) {
    setFlaggingAssignmentId(task.assignment_id)
    try {
      await apiFetch(`/assignments/${task.assignment_id}/flag-missing-template`, {
        method: 'POST',
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          ...(usesOrderConcurrency ? { expected_version: task.order.version } : {}),
        }),
      })
      await loadTasks()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể gắn cờ thiếu temp.')
    } finally {
      setFlaggingAssignmentId(null)
    }
  }

  async function startProcessing(task: Task) {
    setStartingAssignmentId(task.assignment_id)
    try {
      await apiFetch(`/assignments/${task.assignment_id}/start`, {
        method: 'POST',
        body: JSON.stringify({
          request_id: crypto.randomUUID(),
          ...(usesOrderConcurrency ? { expected_version: task.order.version } : {}),
        }),
      })
      await loadTasks()
      window.dispatchEvent(new CustomEvent('orders-updated'))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể bắt đầu xử lý đơn.')
    } finally {
      setStartingAssignmentId(null)
    }
  }

  useEffect(() => {
    if (!usesOrderConcurrency) return
    const lockedTasks = tasks.filter((task) => task.order.processing_lock_owned_by_me)
    if (!lockedTasks.length) return
    const heartbeat = () => {
      lockedTasks.forEach((task) => {
        void apiFetch<{ version: number; processing_lock_expires_at: string }>(`/assignments/${task.assignment_id}/processing-lease/heartbeat`, {
          method: 'POST',
          body: JSON.stringify({ expected_version: task.order.version }),
        }).then((result) => {
          setTasks((current) => current.map((item) => item.assignment_id === task.assignment_id
            ? { ...item, order: { ...item.order, version: result.version, processing_lock_expires_at: result.processing_lock_expires_at } }
            : item))
        }).catch(() => { void loadTasks() })
      })
    }
    const interval = window.setInterval(heartbeat, 5 * 60 * 1000)
    return () => window.clearInterval(interval)
  }, [tasks, usesOrderConcurrency])

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
          {pendingTemplateTasks.length > 0 && (
            <section className="rounded-xl border border-rose-200 bg-rose-50/50 p-4 space-y-3">
              <div className="flex items-center gap-2 text-rose-800">
                <Flag className="h-4 w-4" />
                <h3 className="text-sm font-bold">Chờ cập nhật ({pendingTemplateTasks.length})</h3>
              </div>
              <p className="text-xs text-rose-700">Các đơn này đã được báo thiếu temp. Chờ Admin bổ sung link hoặc ghi chú rồi sẽ tự quay lại To-do.</p>
              {pendingTemplateTasks.map((task) => (
                <div key={task.assignment_id} className="rounded-lg border border-rose-200 bg-white p-3 text-xs">
                  <Link to={`/orders/${task.order.id}`} className="font-mono font-bold text-[#0052CC] hover:underline">{task.order.external_order_id}</Link>
                  <p className="mt-1 text-slate-600">{task.order.product_name || task.order.sku || 'Đơn thiết kế'}</p>
                  {task.order.designer_note && <p className="mt-2 rounded bg-blue-50 p-2 text-slate-700 whitespace-pre-wrap"><strong>Ghi chú Admin:</strong> {task.order.designer_note}</p>}
                </div>
              ))}
            </section>
          )}

          {activeTasks.length > 0 && <h3 className="text-sm font-bold text-slate-700">To-do ({activeTasks.length})</h3>}
          <div className="space-y-4">
            {paginate(activeTasks, currentPage).map((task) => {
            const statusInfo = getStatusInfo(task.order.state)
            const sourceCount = task.order.source_files?.length ?? 0

            return (
              <article
                key={task.assignment_id}
                onClick={(event) => {
                  if ((event.target as HTMLElement).closest('a,button,input,select,textarea')) return
                  setQuickViewOrderId(task.order.id)
                }}
                title="Click vào dòng để xem nhanh sản phẩm"
                className="cursor-pointer rounded-xl border border-slate-200 bg-white p-5 shadow-xs hover:shadow-md transition-all flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4"
              >
                <div className="flex items-start gap-4 flex-1 min-w-0">
                  {/* Product Thumbnail */}
                  {task.order.thumbnail_url ? (
                    <img
                      src={resolveAssetUrl(task.order.thumbnail_url)}
                      alt={task.order.product_name || 'Ảnh sản phẩm'}
                      title="Click để phóng to ảnh"
                      onClick={(event) => {
                        event.stopPropagation()
                        setSelectedImage(resolveAssetUrl(task.order.thumbnail_url))
                      }}
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
                      <CopyableProductName
                        name={task.order.product_name || task.order.external_order_id}
                        textSize="text-sm font-bold"
                      />
                      <Link
                        to={`/orders/${task.order.id}`}
                        className="text-xs font-semibold text-[#0052CC] hover:underline"
                        title="Xem chi tiết đơn hàng"
                      >
                        (Chi tiết)
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
                      {task.order.processing_lock_owned_by_me && task.order.processing_lock_expires_at && (
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-700 border border-emerald-200">
                          Đang giữ phiên đến {new Date(task.order.processing_lock_expires_at).toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' })}
                        </span>
                      )}
                      {(task.order.fix_return_count || 0) > 0 && (
                        <span className="text-xs font-bold px-2 py-0.5 rounded-md bg-orange-50 text-orange-800 border border-orange-200" title="Số lần Printerval trả đơn về Fix">
                          Fix × {task.order.fix_return_count}
                        </span>
                      )}
                    </div>

                    {task.order.designer_note && (
                      <p className="rounded bg-blue-50 px-2 py-1 text-xs text-slate-700 whitespace-pre-wrap"><strong>Ghi chú Admin:</strong> {task.order.designer_note}</p>
                    )}
                    <div className="flex flex-wrap items-center gap-3 text-xs text-slate-500 font-mono pt-0.5">
                      {task.order.deadline_tacahu && (
                        <span className="flex items-center gap-1">
                          <Clock className="h-3.5 w-3.5 text-amber-600" />
                          <span>Hạn chót Tacahu: {new Date(task.order.deadline_tacahu).toLocaleString('vi-VN')}</span>
                        </span>
                      )}

                      {sourceCount > 0 && (
                        <span className="flex items-center gap-1 text-slate-600 font-semibold bg-slate-100 px-2 py-0.5 rounded border border-slate-200">
                          <FolderArchive className="h-3 w-3 text-slate-500" />
                          <span>{sourceCount} file source</span>
                        </span>
                      )}

                      {/* Image Count & Sync Status Badge */}
                      {(() => {
                        const imgCount = (task.order.product_image_urls && task.order.product_image_urls.length > 0)
                          ? task.order.product_image_urls.length
                          : (task.order.thumbnail_url ? 1 : 0)
                        const isSynced = imgCount > 1
                        return isSynced ? (
                          <span
                            className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200 shadow-2xs"
                            title={`Đã đồng bộ đủ bộ ảnh (${imgCount} ảnh)`}
                          >
                            <span>{imgCount} ảnh</span>
                            <Check className="h-3 w-3 text-emerald-600 stroke-[3]" />
                          </span>
                        ) : (
                          <span
                            className="inline-flex items-center gap-1 text-[10px] font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200 shadow-2xs"
                            title={`Chưa đồng bộ bộ ảnh (${imgCount || 1} ảnh)`}
                          >
                            <span>{imgCount || 1} ảnh</span>
                          </span>
                        )
                      })()}

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
                  {!task.order.processing_lock_owned_by_me && (
                    <button
                      type="button"
                      onClick={() => startProcessing(task)}
                      disabled={startingAssignmentId === task.assignment_id}
                      className="mb-2 inline-flex w-full items-center justify-center gap-1 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-bold text-[#0052CC] hover:bg-blue-100 disabled:opacity-50"
                    >
                      <CheckSquare className="h-3.5 w-3.5" /> {startingAssignmentId === task.assignment_id ? 'Đang giữ phiên…' : 'Bắt đầu xử lý'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => flagMissingTemplate(task)}
                    disabled={flaggingAssignmentId === task.assignment_id}
                    className="mb-2 inline-flex w-full items-center justify-center gap-1 rounded-lg border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs font-bold text-rose-700 hover:bg-rose-100 disabled:opacity-50"
                  >
                    <Flag className="h-3.5 w-3.5" /> {flaggingAssignmentId === task.assignment_id ? 'Đang báo…' : 'Báo thiếu temp'}
                  </button>
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
            totalItems={activeTasks.length}
            currentPage={currentPage}
            onPageChange={setCurrentPage}
          />
        </>
      )}
    </DashboardLayout>
  )
}
