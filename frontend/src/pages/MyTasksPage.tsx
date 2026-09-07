import { useEffect, useState } from 'react'
import { ApiError, apiFetch } from '../api/client'
import { useAuth } from '../auth/AuthContext'

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
    deadline_at_ext: string | null
    order_note: string
    custom_config: Record<string, unknown> | null
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

  async function loadTasks() {
    const data = await apiFetch<{ tasks: Task[] }>('/my-tasks')
    setTasks(data.tasks)
  }

  useEffect(() => {
    loadTasks().catch((caught) => {
      setError(caught instanceof ApiError ? caught.message : 'Không tải được task.')
    })
  }, [])

  async function mutate(assignmentId: string, path: string, body: Record<string, string>) {
    setBusyAssignment(assignmentId)
    setError(null)
    try {
      await apiFetch(path, { method: 'POST', body: JSON.stringify(body) })
      await loadTasks()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Không thể cập nhật task.')
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
      setError(caught instanceof ApiError ? caught.message : 'Không thể cập nhật tiến độ.')
    } finally {
      setBusyAssignment(null)
    }
  }

  if (user?.role !== 'designer') {
    return <div className="p-6">Trang này dành cho designer.</div>
  }

  return (
    <main className="p-6 max-w-5xl">
      <h1 className="text-xl font-bold mb-4">Task của tôi</h1>
      {error && <p className="mb-4 text-red-600">{error}</p>}
      {tasks.length === 0 && <p>Chưa có task đang hoạt động.</p>}
      <div className="grid gap-4">
        {tasks.map((task) => {
          const busy = busyAssignment === task.assignment_id
          const canStart = task.order.state === 'ASSIGNED' || task.order.state === 'REVISION_REQUESTED'
          const canSubmit = task.order.state === 'IN_PROGRESS'
          return (
            <article key={task.assignment_id} className="border rounded p-4 bg-white">
              <div className="flex gap-4">
                {task.order.thumbnail_url && (
                  <img src={task.order.thumbnail_url} alt="" className="h-24 w-24 object-cover" />
                )}
                <div className="flex-1">
                  <h2 className="font-bold">{task.order.external_order_id}</h2>
                  <p>{task.order.product_name ?? task.order.sku ?? 'Không có tên sản phẩm'}</p>
                  <p className="text-sm text-gray-600">Trạng thái: {task.order.state}</p>
                  {task.order.deadline_at_ext && (
                    <p className="text-sm text-gray-600">Deadline: {task.order.deadline_at_ext}</p>
                  )}
                </div>
              </div>
              {task.order.order_note && <p className="mt-3 whitespace-pre-wrap">{task.order.order_note}</p>}

              <div className="mt-3 flex flex-wrap gap-2 items-center">
                <span className="text-sm">Tiến độ:</span>
                {(Object.keys(subStatusLabels) as (keyof typeof subStatusLabels)[]).map((status) => (
                  <button
                    key={status}
                    type="button"
                    disabled={busy || task.sub_status === status}
                    className="border px-2 py-1 text-sm disabled:bg-gray-100"
                    onClick={() => changeSubStatus(task.assignment_id, status)}
                  >
                    {subStatusLabels[status]}
                  </button>
                ))}
                {canStart && (
                  <button
                    type="button"
                    disabled={busy}
                    className="bg-blue-600 text-white px-3 py-1 disabled:opacity-50"
                    onClick={() => mutate(
                      task.assignment_id,
                      `/assignments/${task.assignment_id}/start`,
                      { request_id: crypto.randomUUID() },
                    )}
                  >
                    {task.order.state === 'REVISION_REQUESTED' ? 'Bắt đầu sửa' : 'Bắt đầu làm'}
                  </button>
                )}
              </div>

              {task.result_versions.length > 0 && (
                <section className="mt-4 border-t pt-3">
                  <h3 className="font-semibold">Các bản đã nộp</h3>
                  <ul className="list-disc ml-5 text-sm">
                    {task.result_versions.map((version) => (
                      <li key={version.id}>
                        <a className="underline" href={version.drive_url} target="_blank" rel="noreferrer">
                          Bản {version.version_marker}
                        </a>
                        {version.qc_feedback && ` — Feedback QC: ${version.qc_feedback}`}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {canSubmit && (
                <form
                  className="mt-4 border-t pt-3 flex flex-wrap gap-2"
                  onSubmit={(event) => {
                    event.preventDefault()
                    const driveUrl = driveUrls[task.assignment_id]?.trim()
                    if (!driveUrl) {
                      setError('Hãy dán link Google Drive trước khi nộp.')
                      return
                    }
                    mutate(task.assignment_id, `/assignments/${task.assignment_id}/results`, {
                      drive_url: driveUrl,
                      request_id: crypto.randomUUID(),
                    })
                  }}
                >
                  <label className="sr-only" htmlFor={`drive-${task.assignment_id}`}>Link Google Drive</label>
                  <input
                    id={`drive-${task.assignment_id}`}
                    className="border p-1 flex-1 min-w-72"
                    placeholder="Link Google Drive kết quả"
                    value={driveUrls[task.assignment_id] ?? ''}
                    onChange={(event) => setDriveUrls((urls) => ({
                      ...urls, [task.assignment_id]: event.target.value,
                    }))}
                  />
                  <button
                    type="submit"
                    disabled={busy}
                    className="bg-green-600 text-white px-3 py-1 disabled:opacity-50"
                  >
                    Nộp kết quả
                  </button>
                </form>
              )}
            </article>
          )
        })}
      </div>
    </main>
  )
}
