import { Link, useLocation } from 'react-router-dom'
import { BarChart3, Columns3, ListOrdered, Menu, UserCheck, WalletCards } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'

interface MobileBottomNavigationProps {
  onOpenNavigation: () => void
}

type MobileNavItem = {
  label: string
  path: string
  icon: typeof ListOrdered
}

export function MobileBottomNavigation({ onOpenNavigation }: MobileBottomNavigationProps) {
  const { user } = useAuth()
  const location = useLocation()

  if (!user) return null

  const items: MobileNavItem[] = user.role === 'admin'
    ? [
        { label: 'Đơn hàng', path: '/orders', icon: ListOrdered },
        { label: 'Tiến độ', path: '/designer-board', icon: UserCheck },
        { label: 'Board', path: '/kanban', icon: Columns3 },
        { label: 'Tài chính', path: '/finance', icon: WalletCards },
      ]
    : user.role === 'support'
      ? [
          { label: 'Đơn hàng', path: '/orders', icon: ListOrdered },
          { label: 'Tài chính', path: '/finance', icon: WalletCards },
        ]
      : user.role === 'designer-trello'
        ? [
            { label: 'Board', path: '/kanban', icon: Columns3 },
            { label: 'Đơn hàng', path: '/orders', icon: ListOrdered },
            { label: 'Tài chính', path: '/finance', icon: WalletCards },
          ]
        : [
            { label: 'Đơn hàng', path: '/orders', icon: ListOrdered },
            { label: 'Tài chính', path: '/finance', icon: BarChart3 },
          ]

  return (
    <nav aria-label="Điều hướng điện thoại" className="fixed inset-x-0 bottom-0 z-40 flex h-[calc(4.5rem+env(safe-area-inset-bottom))] items-start border-t border-slate-200 bg-white/95 px-2 pt-2 shadow-[0_-8px_24px_rgba(15,23,42,0.08)] backdrop-blur md:hidden">
      {items.map((item) => {
        const Icon = item.icon
        const isActive = location.pathname === item.path
        return (
          <Link
            key={item.path}
            to={item.path}
            className={`flex min-w-0 flex-1 flex-col items-center gap-1 rounded-lg px-1 py-1 text-[10px] font-semibold ${
              isActive ? 'text-[#0052CC]' : 'text-slate-500'
            }`}
          >
            <span className={`rounded-lg p-1.5 ${isActive ? 'bg-blue-50' : ''}`}><Icon className="h-4 w-4" /></span>
            <span className="truncate">{item.label}</span>
          </Link>
        )
      })}
      <button type="button" onClick={onOpenNavigation} className="flex min-w-0 flex-1 flex-col items-center gap-1 rounded-lg px-1 py-1 text-[10px] font-semibold text-slate-500" aria-label="Mở thêm điều hướng">
        <span className="rounded-lg p-1.5"><Menu className="h-4 w-4" /></span>
        <span>Thêm</span>
      </button>
    </nav>
  )
}
