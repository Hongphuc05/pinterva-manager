import { useCallback, useEffect, useState } from 'react'
import { Loader2, RefreshCw, X } from 'lucide-react'
import { cancelJob, fetchJobs } from '../api'
import type { Job } from '../types'
import { useToast } from '../toast'

export const STATUS: Record<string, { label: string; tone: string }> = {
  queued: { label: 'Đang chờ', tone: 'bg-amber-50 text-amber-700 ring-amber-200' },
  running: { label: 'Đang chạy', tone: 'bg-blue-50 text-blue-700 ring-blue-200' },
  completed: { label: 'Hoàn tất', tone: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
  failed: { label: 'Lỗi / hủy', tone: 'bg-red-50 text-red-700 ring-red-200' },
}

export const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('vi-VN', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'

export function JobsView({ onOpen }: { onOpen: (jobId: string) => void }) {
  const toast = useToast()
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setJobs(await fetchJobs(50))
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    } finally {
      setLoading(false)
    }
  }, [toast])

  useEffect(() => {
    void load()
  }, [load])

  const cancel = async (job: Job) => {
    if (!window.confirm(`Hủy job ${job.requested_count} đơn? Phải bấm Có trên Telegram lại nếu muốn so sánh tiếp.`)) return
    try {
      await cancelJob(job.id)
      toast('Đã hủy job.')
      await load()
    } catch (e) {
      toast(e instanceof Error ? e.message : String(e), 'error')
    }
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <h2 className="text-sm font-bold text-slate-900">Lịch sử job</h2>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />Làm mới
        </button>
      </div>
      {!jobs ? (
        <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />Đang tải…</div>
      ) : jobs.length === 0 ? (
        <p className="px-4 py-12 text-center text-sm text-slate-500">Chưa có job nào.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="bg-slate-50 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">Thời gian</th>
                <th className="px-4 py-2">Trạng thái</th>
                <th className="px-4 py-2 text-right">Đơn</th>
                <th className="px-4 py-2 text-right">Nghi trùng</th>
                <th className="px-4 py-2 text-right">Lỗi</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {jobs.map((job) => {
                const status = STATUS[job.status] ?? STATUS.queued
                const active = job.status === 'queued' || job.status === 'running'
                return (
                  <tr key={job.id} className="hover:bg-slate-50">
                    <td className="px-4 py-2.5 font-medium text-slate-800">{when(job.created_at)}</td>
                    <td className="px-4 py-2.5">
                      <span className={`rounded-full px-2.5 py-0.5 text-[11px] font-bold ring-1 ${status.tone}`}>{status.label}</span>
                    </td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{job.processed_count}/{job.requested_count}</td>
                    <td className="px-4 py-2.5 text-right tabular-nums">{job.duplicate_count}</td>
                    <td className={`px-4 py-2.5 text-right tabular-nums ${job.error_count ? 'font-semibold text-red-600' : 'text-slate-400'}`}>{job.error_count}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => onOpen(job.id)}
                          className="rounded-lg border border-slate-300 bg-white px-3 py-1 text-xs font-semibold text-slate-700 transition hover:bg-slate-50"
                        >
                          Mở duyệt
                        </button>
                        {active && (
                          <button
                            type="button"
                            onClick={() => void cancel(job)}
                            className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-2.5 py-1 text-xs font-semibold text-red-600 transition hover:bg-red-50"
                          >
                            <X className="h-3 w-3" />Hủy
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
