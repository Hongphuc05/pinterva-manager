import { useEffect, useRef, useState } from 'react'
import { AlertCircle, AlertTriangle, Bell, CheckCircle2, Info, Trash2 } from 'lucide-react'
import { useToast } from '../context/ToastContext'

const ICONS = {
  success: <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0 mt-0.5" />,
  error: <AlertCircle className="h-4 w-4 text-rose-600 shrink-0 mt-0.5" />,
  warning: <AlertTriangle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />,
  info: <Info className="h-4 w-4 text-[#0052CC] shrink-0 mt-0.5" />,
}

function timeAgo(at: number, now = Date.now()): string {
  const minutes = Math.floor((now - at) / 60_000)
  if (minutes < 1) return 'vừa xong'
  if (minutes < 60) return `${minutes} phút trước`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} giờ trước`
  return `${Math.floor(hours / 24)} ngày trước`
}

/** The bell in the top bar: every toast of the last three days, to read again after it has gone. */
export function NotificationBell() {
  const { notifications, unreadCount, markNotificationsRead, clearNotifications } = useToast()
  const [open, setOpen] = useState(false)
  const rootRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    markNotificationsRead()
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open, markNotificationsRead, notifications.length])

  return (
    <div className="relative" ref={rootRef}>
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="relative p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors"
        aria-label={unreadCount > 0 ? `Thông báo, ${unreadCount} chưa xem` : 'Thông báo'}
        aria-expanded={open}
      >
        <Bell className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute top-0.5 right-0.5 min-w-4 h-4 px-1 rounded-full bg-amber-500 text-[10px] font-bold leading-4 text-white text-center ring-2 ring-white">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-2 z-[60] w-[min(24rem,calc(100vw-2rem))] rounded-2xl border border-slate-200 bg-white shadow-xl"
          role="dialog"
          aria-label="Thông báo"
        >
          <div className="flex items-center justify-between gap-2 border-b border-slate-100 px-3.5 py-2.5">
            <p className="text-xs font-bold text-slate-800">Thông báo (giữ 3 ngày)</p>
            {notifications.length > 0 && (
              <button
                type="button"
                onClick={clearNotifications}
                className="inline-flex items-center gap-1 text-[11px] font-semibold text-slate-500 hover:text-red-600"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Xóa tất cả
              </button>
            )}
          </div>
          {notifications.length === 0 ? (
            <p className="px-3.5 py-6 text-center text-xs text-slate-500">Chưa có thông báo nào trong 3 ngày qua.</p>
          ) : (
            <ul className="max-h-[70vh] divide-y divide-slate-100 overflow-y-auto">
              {notifications.map((item) => (
                <li key={item.id} className="flex items-start gap-2.5 px-3.5 py-2.5">
                  {ICONS[item.type] ?? ICONS.info}
                  <div className="min-w-0 flex-1">
                    <p className="break-words text-xs font-medium leading-relaxed text-slate-800 select-text">{item.message}</p>
                    <p className="mt-0.5 text-[10px] text-slate-400" title={new Date(item.at).toLocaleString('vi-VN')}>
                      {timeAgo(item.at)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
