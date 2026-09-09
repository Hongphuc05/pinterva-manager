import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api/client'
import { getStatusInfo } from '../utils/statusTranslation'
import {
  X,
  Clock,
  User,
  Shield,
  ExternalLink,
  Loader2,
  CheckCircle2,
  AlertTriangle,
  Send,
  FileEdit,
  UserPlus,
  ArrowRight
} from 'lucide-react'

export type OrderTimelineEvent = {
  id: string
  created_at: string
  from_state: string | null
  to_state: string
  actor_id: string | null
  actor_name: string | null
  actor_role: string | null
  action: string | null
  description: string | null
  designer_name: string | null
  evidence: any
}

interface OrderHistoryTimelineModalProps {
  isOpen: boolean
  onClose: () => void
  orderId: string
  externalOrderId: string
  productName?: string | null
}

export function OrderHistoryTimelineModal({
  isOpen,
  onClose,
  orderId,
  externalOrderId,
  productName,
}: OrderHistoryTimelineModalProps) {
  const [events, setEvents] = useState<OrderTimelineEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!isOpen || !orderId) return
    setLoading(true)
    setError(null)
    apiFetch<OrderTimelineEvent[]>(`/orders/${orderId}/history`)
      .then((data) => {
        setEvents(data)
      })
      .catch((err: any) => {
        setError(err.message || 'Không thể tải lịch sử đơn hàng.')
      })
      .finally(() => {
        setLoading(false)
      })
  }, [isOpen, orderId])

  if (!isOpen) return null

  function getActionBadge(event: OrderTimelineEvent) {
    const act = (event.action || '').toUpperCase()
    if (act === 'APPROVE_DONE') {
      return {
        icon: CheckCircle2,
        color: 'text-emerald-700 bg-emerald-100 border-emerald-300',
        dot: 'bg-emerald-500',
      }
    }
    if (act === 'REQUEST_FIX') {
      return {
        icon: AlertTriangle,
        color: 'text-orange-700 bg-orange-100 border-orange-300',
        dot: 'bg-orange-500',
      }
    }
    if (act === 'SUBMIT_REVIEW') {
      return {
        icon: Send,
        color: 'text-purple-700 bg-purple-100 border-purple-300',
        dot: 'bg-purple-500',
      }
    }
    if (act === 'ASSIGN' || act === 'REASSIGN') {
      return {
        icon: UserPlus,
        color: 'text-blue-700 bg-blue-100 border-blue-300',
        dot: 'bg-blue-500',
      }
    }
    if (act === 'REVERT_TO_DOING' || act === 'START_DOING') {
      return {
        icon: FileEdit,
        color: 'text-sky-700 bg-sky-100 border-sky-300',
        dot: 'bg-sky-500',
      }
    }
    return {
      icon: Clock,
      color: 'text-slate-700 bg-slate-100 border-slate-300',
      dot: 'bg-slate-400',
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-150"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl max-h-[85vh] rounded-2xl bg-white shadow-2xl border border-slate-200 flex flex-col overflow-hidden animate-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="p-4 border-b border-slate-100 bg-slate-50/80 flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-9 w-9 rounded-xl bg-blue-100 text-[#0052CC] flex items-center justify-center shrink-0">
              <Clock className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-sm text-slate-900 font-mono">{externalOrderId}</h3>
                <Link
                  to={`/orders/${orderId}`}
                  onClick={onClose}
                  className="text-[11px] text-[#0052CC] hover:underline flex items-center gap-0.5 font-medium"
                >
                  <span>Xem chi tiết</span>
                  <ExternalLink className="h-2.5 w-2.5" />
                </Link>
              </div>
              {productName && (
                <p className="text-xs text-slate-500 truncate mt-0.5">{productName}</p>
              )}
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors cursor-pointer"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 p-5 overflow-y-auto space-y-4">
          {loading ? (
            <div className="py-12 text-center text-slate-400">
              <Loader2 className="h-7 w-7 animate-spin mx-auto mb-2 text-[#0052CC]" />
              <p className="text-xs font-medium">Đang tải toàn bộ lịch sử tiến độ đơn hàng...</p>
            </div>
          ) : error ? (
            <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs">
              {error}
            </div>
          ) : events.length === 0 ? (
            <div className="py-12 text-center text-slate-400">
              <Clock className="h-8 w-8 mx-auto mb-2 opacity-30" />
              <p className="text-xs font-semibold text-slate-600">Chưa có bản ghi lịch sử nào cho đơn này</p>
            </div>
          ) : (
            <div className="relative pl-6 space-y-6 before:absolute before:left-2.5 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-200">
              {events.map((event, idx) => {
                const badge = getActionBadge(event)
                const fromInfo = event.from_state ? getStatusInfo(event.from_state) : null
                const toInfo = getStatusInfo(event.to_state)
                const driveLink = event.evidence?.drive_url

                return (
                  <div key={event.id || idx} className="relative group">
                    {/* Dot on Timeline */}
                    <div
                      className={`absolute -left-[19px] top-1.5 h-3.5 w-3.5 rounded-full border-2 border-white shadow-xs ${badge.dot}`}
                    />

                    {/* Event Card */}
                    <div className="p-3.5 rounded-xl border border-slate-200 bg-white hover:border-slate-300 transition-all shadow-2xs space-y-2">
                      {/* Top row: Timestamp & Actor */}
                      <div className="flex items-center justify-between gap-2 text-xs flex-wrap">
                        <div className="flex items-center gap-1.5 text-slate-500 font-mono text-[11px]">
                          <Clock className="h-3 w-3 text-slate-400" />
                          <span>{new Date(event.created_at).toLocaleString('vi-VN')}</span>
                        </div>

                        {event.actor_name && (
                          <div className="flex items-center gap-1.5">
                            <span
                              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                                event.actor_role === 'admin'
                                  ? 'bg-purple-100 text-purple-800'
                                  : 'bg-blue-100 text-blue-800'
                              }`}
                            >
                              {event.actor_role === 'admin' ? (
                                <Shield className="h-2.5 w-2.5" />
                              ) : (
                                <User className="h-2.5 w-2.5" />
                              )}
                              <span>{event.actor_role || 'User'}</span>
                            </span>
                            <span className="font-semibold text-slate-800 text-xs">{event.actor_name}</span>
                          </div>
                        )}
                      </div>

                      {/* Middle row: Description */}
                      <div className="text-xs text-slate-800 font-medium leading-relaxed">
                        {event.description || (
                          <span>
                            Chuyển trạng thái từ{' '}
                            <strong className="text-slate-600">{fromInfo ? fromInfo.label : 'Mới'}</strong> sang{' '}
                            <strong className="text-[#0052CC]">{toInfo.label}</strong>
                          </span>
                        )}
                      </div>

                      {/* Status Badges Flow */}
                      <div className="flex items-center gap-2 text-[11px] pt-1">
                        {fromInfo ? (
                          <span
                            className={`px-2 py-0.5 rounded-md font-bold border text-[10px] ${fromInfo.badgeClass}`}
                          >
                            {fromInfo.label}
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-md font-semibold text-[10px] bg-slate-100 text-slate-500 border border-slate-200">
                            Mới tạo
                          </span>
                        )}
                        <ArrowRight className="h-3 w-3 text-slate-400" />
                        <span
                          className={`px-2 py-0.5 rounded-md font-bold border text-[10px] ${toInfo.badgeClass}`}
                        >
                          {toInfo.label}
                        </span>
                      </div>

                      {/* Drive Link (if submitted) */}
                      {driveLink && (
                        <div className="pt-2 border-t border-slate-100">
                          <a
                            href={driveLink}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1.5 text-xs font-mono text-[#0052CC] hover:underline font-semibold bg-blue-50/60 px-2.5 py-1 rounded-lg border border-blue-200 break-all"
                          >
                            <ExternalLink className="h-3 w-3 shrink-0" />
                            <span className="truncate">Link Drive bài nộp: {driveLink}</span>
                          </a>
                        </div>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-3.5 border-t border-slate-100 bg-slate-50 flex items-center justify-between text-xs text-slate-500">
          <span>Tổng số sự kiện: <strong>{events.length}</strong></span>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg text-xs font-semibold text-slate-600 hover:text-slate-900 bg-white border border-slate-200 hover:bg-slate-100 transition-colors cursor-pointer"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  )
}
