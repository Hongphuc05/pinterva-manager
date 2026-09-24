import type { ReactNode } from 'react'

export type View = 'review' | 'search'

const VIEWS: { key: View; label: string }[] = [
  { key: 'review', label: 'Duyệt kết quả' },
  { key: 'search', label: 'Tìm ảnh' },
]

interface LayoutProps {
  connected: boolean | null
  view: View
  onView: (view: View) => void
  right?: ReactNode
  children: ReactNode
}

export function Layout({ connected, view, onView, right, children }: LayoutProps) {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 border-b border-line bg-bg/95 backdrop-blur">
        <div className="mx-auto flex h-11 max-w-6xl items-center gap-3 px-4">
          <b className="text-sm font-semibold">Duyệt trùng</b>
          <nav className="flex gap-1" role="tablist" aria-label="Chức năng">
            {VIEWS.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={view === key}
                onClick={() => onView(key)}
                className={`h-7 cursor-pointer rounded px-2.5 text-xs font-medium transition ${
                  view === key ? 'bg-raised text-fg' : 'text-dim hover:text-fg'
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
          <span className="inline-flex items-center gap-1.5 text-xs text-dim">
            <i className={`size-1.5 rounded-full ${connected === false ? 'bg-bad' : connected ? 'bg-ok' : 'bg-dim'}`} />
            {connected === null ? 'Đang kết nối' : connected ? 'DB' : 'Mất kết nối'}
          </span>
          <div className="flex-1" />
          {right}
          <nav className="flex gap-3 text-xs text-dim">
            <a href="/index.html" className="hover:text-fg">So sánh 1-1</a>
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-4">{children}</main>
    </div>
  )
}
