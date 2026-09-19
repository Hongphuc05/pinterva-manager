import { useState, type ReactNode } from 'react'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'
import { MobileBottomNavigation } from './MobileBottomNavigation'

interface DashboardLayoutProps {
  children: ReactNode
}

export function DashboardLayout({ children }: DashboardLayoutProps) {
  const [mobileNavigationOpen, setMobileNavigationOpen] = useState(false)

  return (
    <div className="min-h-screen bg-[hsl(var(--tertiary))] text-[hsl(var(--foreground))] md:flex">
      <Sidebar mobileOpen={mobileNavigationOpen} onMobileClose={() => setMobileNavigationOpen(false)} />
      {mobileNavigationOpen && (
        <button
          type="button"
          aria-label="Đóng điều hướng"
          className="fixed inset-0 z-40 bg-slate-950/40 backdrop-blur-[1px] md:hidden"
          onClick={() => setMobileNavigationOpen(false)}
        />
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <Topbar onOpenNavigation={() => setMobileNavigationOpen(true)} />
        <main className="flex-1 space-y-4 overflow-y-auto p-3 pb-24 sm:space-y-5 sm:p-5 sm:pb-24 md:space-y-6 md:p-6 md:pb-6 xl:p-8">
          {children}
        </main>
      </div>
      <MobileBottomNavigation onOpenNavigation={() => setMobileNavigationOpen(true)} />
    </div>
  )
}
