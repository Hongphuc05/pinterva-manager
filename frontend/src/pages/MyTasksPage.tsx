import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiFetch } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { DashboardLayout } from '../components/DashboardLayout'
import { SourceFilesCard, type SourceFile } from '../components/SourceFilesCard'
import { TemplateModal, type TemplateJob } from '../components/TemplateModal'
import { 
  CheckSquare, 
  Clock, 
  ExternalLink, 
  Send, 
  Play, 
  AlertCircle, 
  FileText, 
  History, 
  Package
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
    has_template: boolean
    template_jobs: TemplateJob[] | null
    deadline_at_ext: string | null
    note_outsource: string | null
    order_note: string
    custom_config: Record<string, unknown> | null
    sku_image_url: string | null
    external_order_url: string | null
    source_files: SourceFile[] | null
    source_download_all_url: string | null
    design_tool_url: string | null
  }
  result_versions: ResultVersion[]
}

const subStatusLabels = { doing: 'Đang làm', fixing: 'Đang sửa', done: 'Đã xong' }

export function MyTasksPage() {
  const { user } = useAuth()
  const [tasks, setTasks] = useState<Task[]>([])
  const [driveUrls, setDriveUrls] = useState<Record<string, string>>({})
  const [busyAssignment, setBusyAssignment] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

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

  async function mutate(assignmentId: string, path: string, body: Record<string, string>) {
    setBusyAssignment(assignmentId)
    setError(null)
    try {
      await apiFetch(path, { method: 'POST', body: JSON.stringify(body) })
      await loadTasks()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể cập nhật trạng thái task.')
    } finally {
      setBusyAssignment(null)
    }
  }

  async function changeSubStatus(assignmentId: string, subStatus: keyof typeof subStatusLabels) {
    setBusyAssignment(assignmentId)
    setError(null)
    try {
      await apiFetch(`/assignments/${assignmentId}/sub-status`, {
        method: 'PATCH',
        body: JSON.stringify({ sub_status: subStatus, request_id: crypto.randomUUID() }),
      })
      await loadTasks()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể cập nhật tiến độ sub-status.')
    } finally {
      setBusyAssignment(null)
    }
  }

  const [activeTemplateJobs, setActiveTemplateJobs] = useState<{ jobs: TemplateJob[]; orderId: string } | null>(null)

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
      {/* Template Modal */}
      <TemplateModal
        isOpen={!!activeTemplateJobs}
        onClose={() => setActiveTemplateJobs(null)}
        templateJobs={activeTemplateJobs?.jobs}
        orderId={activeTemplateJobs?.orderId}
      />

      {/* Header Info */}
      <div className="rounded-xl border border-[hsl(var(--border))] bg-white p-5 shadow-xs flex items-center justify-between">
        <div>
          <h2 className="text-base font-bold text-slate-800 flex items-center gap-2">
            <CheckSquare className="h-5 w-5 text-[#0052CC]" />
            <span>Nhiệm Vụ Thiết Kế Của Tôi (My Tasks)</span>
          </h2>
          <p className="text-xs text-slate-500 mt-0.5">Danh sách các đơn hàng được gán cho bạn. Đổi tiến độ & nộp link Google Drive khi hoàn thành</p>
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
          {[1, 2].map((n) => (
            <div key={n} className="rounded-xl border border-slate-200 bg-white p-6 h-48 animate-pulse space-y-3">
              <div className="h-6 bg-slate-200 rounded-md w-1/3"></div>
              <div className="h-4 bg-slate-100 rounded-md w-2/3"></div>
            </div>
          ))}
        </div>
      ) : tasks.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-300 bg-white p-12 text-center text-slate-400">
          <CheckSquare className="h-12 w-12 mx-auto mb-3 opacity-25 text-slate-500" />
          <h3 className="text-sm font-semibold text-slate-700">Chưa có task nào được gán</h3>
          <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">Vào trang "Phân Bổ Kéo-Thả" để nhận đơn mới hoặc chờ Admin gán công việc cho bạn.</p>
        </div>
      ) : (
        <div className="space-y-5">
          {tasks.map((task) => {
            const busy = busyAssignment === task.assignment_id
            const canStart = task.order.state === 'ASSIGNED' || task.order.state === 'REVISION_REQUESTED'
            const canSubmit = task.order.state === 'IN_PROGRESS'

            return (
              <article key={task.assignment_id} className="rounded-xl border border-slate-200 bg-white p-6 shadow-xs hover:shadow-md transition-shadow space-y-4">
                <div className="flex flex-col sm:flex-row sm:items-start gap-4">
                  {task.order.thumbnail_url ? (
                    <img src={task.order.thumbnail_url} alt="" className="h-20 w-20 rounded-xl object-cover border border-slate-200 shrink-0" />
                  ) : (
                    <div className="h-20 w-20 rounded-xl bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-400 shrink-0">
                      <Package className="h-8 w-8" />
                    </div>
                  )}

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2">
                        <Link to={`/orders/${task.order.id}`} className="font-mono text-base font-bold text-[#0052CC] hover:underline">
                          {task.order.external_order_id}
                        </Link>
                        {task.order.sku_image_url && (
                          <a
                            href={task.order.sku_image_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs font-bold text-[#0052CC] hover:underline flex items-center gap-0.5 px-2 py-0.5 rounded bg-blue-50 border border-blue-100"
                          >
                            <span>Image</span>
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                        {task.order.external_order_url && (
                          <a
                            href={task.order.external_order_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-xs font-bold text-[#0052CC] hover:underline flex items-center gap-0.5 px-2 py-0.5 rounded bg-blue-50 border border-blue-100"
                          >
                            <span>Order</span>
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        )}
                      </div>
                      <span className="text-xs font-semibold px-2.5 py-1 rounded-md bg-slate-100 text-slate-700 border border-slate-200">
                        {task.order.state}
                      </span>
                    </div>

                    <p className="text-xs font-medium text-slate-700 mt-1">
                      {task.order.product_name ?? task.order.sku ?? 'Đơn thiết kế 2D'}
                    </p>

                    <div className="flex flex-wrap items-center gap-4 mt-2 text-xs text-slate-500 font-mono">
                      {task.order.deadline_at_ext && (
                        <span className="flex items-center gap-1">
                          <Clock className="h-3.5 w-3.5 text-amber-600" />
                          <span>Deadline: {new Date(task.order.deadline_at_ext).toLocaleString('vi-VN')}</span>
                        </span>
                      )}
                      {task.order.template_jobs && task.order.template_jobs.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setActiveTemplateJobs({ jobs: task.order.template_jobs!, orderId: task.order.external_order_id })}
                          className="inline-flex items-center gap-1 px-2.5 py-0.5 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-md transition-colors cursor-pointer"
                        >
                          <FileText className="h-3 w-3" />
                          <span>Xem template</span>
                        </button>
                      )}
                    </div>
                  </div>
                </div>

                {/* Customer Source Files */}
                <SourceFilesCard
                  sourceFiles={task.order.source_files}
                  downloadAllUrl={task.order.source_download_all_url}
                />

                {/* Order Note */}
                {task.order.order_note && (
                  <div className="p-3.5 rounded-xl bg-slate-50 border border-slate-200 text-xs text-slate-600 space-y-1">
                    <span className="font-bold text-slate-700 block flex items-center gap-1">
                      <FileText className="h-3.5 w-3.5 text-slate-500" />
                      Ghi chú đơn hàng:
                    </span>
                    <p className="whitespace-pre-wrap font-mono text-[11px] text-slate-700">{task.order.order_note}</p>
                  </div>
                )}

                {/* Progress Control Buttons */}
                <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-slate-100">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-semibold text-slate-500">Cập nhật tiến độ:</span>
                    {(Object.keys(subStatusLabels) as (keyof typeof subStatusLabels)[]).map((status) => (
                      <button
                        key={status}
                        type="button"
                        disabled={busy || task.sub_status === status}
                        className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors border ${
                          task.sub_status === status
                            ? 'bg-[#0052CC] text-white border-[#0052CC] shadow-2xs'
                            : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
                        } disabled:opacity-50`}
                        onClick={() => changeSubStatus(task.assignment_id, status)}
                      >
                        {subStatusLabels[status]}
                      </button>
                    ))}
                  </div>

                  {canStart && (
                    <button
                      type="button"
                      disabled={busy}
                      className="px-4 py-2 text-xs font-semibold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-lg transition-colors shadow-2xs flex items-center gap-1.5 disabled:opacity-50"
                      onClick={() => mutate(
                        task.assignment_id,
                        `/assignments/${task.assignment_id}/start`,
                        { request_id: crypto.randomUUID() },
                      )}
                    >
                      <Play className="h-3.5 w-3.5 fill-current" />
                      <span>{task.order.state === 'REVISION_REQUESTED' ? 'Bắt đầu sửa theo QC' : 'Bắt đầu thực hiện'}</span>
                    </button>
                  )}
                </div>

                {/* History Versions */}
                {task.result_versions.length > 0 && (
                  <div className="pt-3 border-t border-slate-100 space-y-2">
                    <h4 className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
                      <History className="h-3.5 w-3.5 text-slate-400" />
                      <span>Lịch sử các bản đã nộp ({task.result_versions.length})</span>
                    </h4>
                    <div className="space-y-2">
                      {task.result_versions.map((version) => (
                        <div key={version.id} className="p-3 rounded-lg bg-slate-50 border border-slate-200 flex items-center justify-between text-xs">
                          <a
                            href={version.drive_url}
                            target="_blank"
                            rel="noreferrer"
                            className="font-mono font-bold text-[#0052CC] hover:underline flex items-center gap-1"
                          >
                            <span>Bản v{version.version_marker}</span>
                            <ExternalLink className="h-3 w-3" />
                          </a>
                          {version.qc_feedback && (
                            <p className="text-amber-800 bg-amber-50 px-2 py-0.5 rounded border border-amber-200 text-[11px] font-medium">
                              QC Feedback: {version.qc_feedback}
                            </p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Submit Drive Link Form */}
                {canSubmit && (
                  <form
                    className="pt-3 border-t border-slate-100 flex flex-col sm:flex-row gap-3"
                    onSubmit={(event: FormEvent) => {
                      event.preventDefault()
                      const driveUrl = driveUrls[task.assignment_id]?.trim()
                      if (!driveUrl) {
                        setError('Hãy dán đường dẫn Google Drive trước khi nộp bài.')
                        return
                      }
                      mutate(task.assignment_id, `/assignments/${task.assignment_id}/results`, {
                        drive_url: driveUrl,
                        request_id: crypto.randomUUID(),
                      })
                    }}
                  >
                    <input
                      id={`drive-${task.assignment_id}`}
                      type="url"
                      required
                      className="flex-1 px-3.5 py-2 text-xs rounded-xl border border-slate-200 bg-slate-50/50 font-mono focus:outline-none focus:border-[#0052CC]"
                      placeholder="https://drive.google.com/file/d/..."
                      value={driveUrls[task.assignment_id] ?? ''}
                      onChange={(event) => setDriveUrls((urls) => ({
                        ...urls, [task.assignment_id]: event.target.value,
                      }))}
                    />
                    <button
                      type="submit"
                      disabled={busy}
                      className="px-5 py-2 text-xs font-semibold text-white bg-emerald-600 hover:bg-emerald-700 rounded-xl transition-colors shadow-2xs flex items-center justify-center gap-1.5 disabled:opacity-50 shrink-0"
                    >
                      <Send className="h-3.5 w-3.5" />
                      <span>Nộp Bài QC</span>
                    </button>
                  </form>
                )}
              </article>
            )
          })}
        </div>
      )}
    </DashboardLayout>
  )
}
