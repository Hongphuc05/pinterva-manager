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
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4500)
  }, [])

  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="fixed bottom-5 right-5 z-[80] flex flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`max-w-sm rounded-lg border border-l-4 bg-white px-3.5 py-2.5 text-[13px] shadow-xl ${
              t.kind === 'error' ? 'border-l-destructive' : 'border-l-accent'
            } border-border`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
