import React, { createContext, useContext, useState, useCallback, useEffect } from 'react'
import { CheckCircle2, AlertCircle, AlertTriangle, Info, X } from 'lucide-react'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: string
  message: string
  type: ToastType
  duration: number
  createdAt: number
}

interface ToastContextType {
  showToast: (message: string, type?: ToastType, duration?: number) => void
  removeToast: (id: string) => void
}

const ToastContext = createContext<ToastContextType | undefined>(undefined)

/** Helper to dispatch toast outside of React component lifecycle */
export function showAppToast(message: string, type: ToastType = 'success', duration = 5000) {
  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('app-toast', {
        detail: { message, type, duration },
      })
    )
  }
}

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<Toast[]>([])

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const showToast = useCallback(
    (message: string, type: ToastType = 'success', duration = 5000) => {
      if (!message || !message.trim()) return
      const id = `${Date.now()}-${Math.random().toString(36).substring(2, 9)}`
      const newToast: Toast = {
        id,
        message: message.trim(),
        type,
        duration,
        createdAt: Date.now(),
      }
      setToasts((prev) => [...prev.slice(-4), newToast]) // Keep at most 5 toasts visible
    },
    []
  )

  // Listen for window 'app-toast' events
  useEffect(() => {
    function handleAppToastEvent(e: Event) {
      const customEvent = e as CustomEvent<{ message: string; type?: ToastType; duration?: number }>
      if (customEvent.detail?.message) {
        showToast(
          customEvent.detail.message,
          customEvent.detail.type || 'success',
          customEvent.detail.duration || 5000
        )
      }
    }

    window.addEventListener('app-toast', handleAppToastEvent)
    return () => window.removeEventListener('app-toast', handleAppToastEvent)
  }, [showToast])

  return (
    <ToastContext.Provider value={{ showToast, removeToast }}>
      {children}
      {/* Toast Popup Container - Bottom Right 5s */}
      <div
        className="fixed bottom-5 right-5 z-[99999] flex flex-col-reverse gap-2.5 pointer-events-none max-w-sm w-[calc(100vw-2.5rem)] sm:w-96"
        aria-live="polite"
      >
        {toasts.map((toast) => (
          <ToastCard key={toast.id} toast={toast} onDismiss={() => removeToast(toast.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const context = useContext(ToastContext)
  if (!context) {
    return {
      showToast: showAppToast,
      removeToast: () => {},
    }
  }
  return context
}

const ToastCard: React.FC<{ toast: Toast; onDismiss: () => void }> = ({ toast, onDismiss }) => {
  const [progress, setProgress] = useState(100)

  useEffect(() => {
    const startTime = Date.now()
    const interval = setInterval(() => {
      const elapsed = Date.now() - startTime
      const remaining = Math.max(0, 100 - (elapsed / toast.duration) * 100)
      setProgress(remaining)
      if (elapsed >= toast.duration) {
        clearInterval(interval)
        onDismiss()
      }
    }, 50)

    return () => clearInterval(interval)
  }, [toast.duration, onDismiss])

  const typeConfig = {
    success: {
      border: 'border-emerald-200 bg-white/95 text-emerald-950 shadow-emerald-500/10',
      bar: 'bg-emerald-500',
      icon: <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0 mt-0.5" />,
    },
    error: {
      border: 'border-rose-200 bg-white/95 text-rose-950 shadow-rose-500/10',
      bar: 'bg-rose-500',
      icon: <AlertCircle className="h-5 w-5 text-rose-600 shrink-0 mt-0.5" />,
    },
    warning: {
      border: 'border-amber-200 bg-white/95 text-amber-950 shadow-amber-500/10',
      bar: 'bg-amber-500',
      icon: <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />,
    },
    info: {
      border: 'border-blue-200 bg-white/95 text-blue-950 shadow-blue-500/10',
      bar: 'bg-[#0052CC]',
      icon: <Info className="h-5 w-5 text-[#0052CC] shrink-0 mt-0.5" />,
    },
  }

  const config = typeConfig[toast.type] || typeConfig.success

  return (
    <div
      className={`pointer-events-auto relative overflow-hidden rounded-2xl border shadow-xl backdrop-blur-md transition-all duration-300 transform animate-in slide-in-from-right-8 fade-in-0 p-3.5 flex items-start gap-3 ${config.border}`}
      role="alert"
    >
      {config.icon}
      <div className="flex-1 min-w-0 pr-1">
        <p className="text-xs font-semibold leading-relaxed text-slate-800 break-words select-text">
          {toast.message}
        </p>
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="text-slate-400 hover:text-slate-700 p-1 rounded-lg hover:bg-slate-100 transition-colors shrink-0 cursor-pointer"
        title="Đóng thông báo"
      >
        <X className="h-4 w-4" />
      </button>

      {/* 5s Auto-dismiss progress line */}
      <div className="absolute bottom-0 left-0 right-0 h-1 bg-slate-100/60 overflow-hidden">
        <div
          className={`h-full transition-all duration-75 ease-linear ${config.bar}`}
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  )
}
