import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

type Kind = 'success' | 'error'
interface Toast {
  id: number
  kind: Kind
  message: string
}

const ToastContext = createContext<(message: string, kind?: Kind) => void>(() => {})
export const useToast = () => useContext(ToastContext)

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const show = useCallback((message: string, kind: Kind = 'success') => {
    const id = Date.now() + Math.random()
    setToasts((prev) => [...prev, { id, kind, message }])
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4000)
  }, [])

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="fixed bottom-4 right-4 z-[80] flex flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`max-w-xs rounded-md border border-line border-l-2 bg-raised px-3 py-2 text-xs shadow-lg ${
              t.kind === 'error' ? 'border-l-bad' : 'border-l-ok'
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
