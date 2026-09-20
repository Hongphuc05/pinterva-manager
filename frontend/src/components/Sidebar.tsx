import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import {
  ListOrdered,
  PackageCheck,
  UserCheck,
  ShieldAlert,
  Users,
  History,
  Coins,
  Columns3,
  Globe,
  FolderGit2,
  X,
} from 'lucide-react'

interface SidebarProps {
  mobileOpen: boolean
  onMobileClose: () => void
}

export function Sidebar({ mobileOpen, onMobileClose }: SidebarProps) {
  const { user } = useAuth()
  const location = useLocation()

  if (!user) return null

  const isAdmin = user.role === 'admin'
  const isTrelloDesigner = user.role === 'designer-trello'
  const isSupport = user.role === 'support'

  const adminSections = [
    {
      label: 'Vận hành',
      items: [
        { label: 'Đơn Hàng', path: '/orders', icon: ListOrdered },
        { label: 'Tiến Độ Team', path: '/designer-board', icon: UserCheck },
        { label: 'Lưu Link Nộp Bài', path: '/designer-submissions', icon: FolderGit2 },
        { label: 'Board Đơn trùng lặp', path: '/kanban', icon: Columns3 },
        { label: 'Mở Hệ Thống Mẹ', path: '/platform-hub', icon: Globe },
      ],
    },
    {
      label: 'Báo cáo',
      items: [
        { label: 'Tài Chính & Công Lao', path: '/finance', icon: Coins },
        { label: 'Lịch Sử Tiến Độ', path: '/order-history', icon: History },
      ],
    },
    {
      label: 'Cài đặt',
      items: [{ label: 'Quản Lý Tài Khoản', path: '/users', icon: Users }],
    },
  ]

  const supportSections = [
    {
      label: 'Vận hành',
      items: [
        { label: 'Đơn Hàng', path: '/orders', icon: ListOrdered },
        { label: 'Lưu Link Nộp Bài', path: '/designer-submissions', icon: FolderGit2 },
        { label: 'Board Đơn trùng lặp', path: '/kanban', icon: Columns3 },
      ],
    },
  ]

  const designerSections = [
    {
      label: 'Công việc',
      items: [
        { label: 'Nhiệm Vụ Của Tôi', path: '/orders', icon: ListOrdered },
        { label: 'Tài Chính', path: '/finance', icon: Coins },
      ],
    },
  ]

  const trelloDesignerSections = [
    {
      label: 'Công việc',
      items: [
        { label: 'Board Đơn trùng lặp', path: '/kanban', icon: Columns3 },
        { label: 'Đơn Hàng', path: '/orders', icon: ListOrdered },
        { label: 'Tài Chính', path: '/finance', icon: Coins },
      ],
    },
  ]

  const navSections = isAdmin ? adminSections : isSupport ? supportSections : isTrelloDesigner ? trelloDesignerSections : designerSections

  return (
    <aside
      aria-label="Điều hướng chính"
      className={`fixed inset-y-0 left-0 z-50 flex h-[100dvh] w-72 shrink-0 flex-col bg-[#0052CC] text-white shadow-lg transition-transform duration-200 ease-out select-none ${
        mobileOpen ? 'translate-x-0' : '-translate-x-full'
      } md:sticky md:top-0 md:w-20 md:translate-x-0 xl:w-64`}
    >
      <div className="flex h-16 items-center gap-3 border-b border-white/15 bg-blue-900/30 px-4 md:justify-center md:px-0 xl:justify-start xl:px-6">
        <div className="rounded-xl bg-white/20 p-2 backdrop-blur-md">
          <PackageCheck className="h-6 w-6 text-white" />
        </div>
        <div className="min-w-0 md:hidden xl:block">
          <h1 className="font-bold text-base tracking-tight text-white leading-none">Tacahu Ops</h1>
          <p className="mt-1 text-[11px] font-medium text-blue-100/70">System Dashboard V1</p>
        </div>
        <button
          type="button"
          onClick={onMobileClose}
          className="ml-auto rounded-lg p-2 text-blue-100 hover:bg-white/10 hover:text-white md:hidden"
          aria-label="Đóng điều hướng"
        >
          <X className="h-5 w-5" />
        </button>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-6 md:px-2 xl:px-3" onClick={onMobileClose}>
        {navSections.map((section) => (
          <section key={section.label} className="mb-5 last:mb-0">
            <div className="px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-blue-200/60 md:sr-only xl:not-sr-only">
              {section.label}
            </div>
            <div className="space-y-1">
              {section.items.map((item) => {
                const Icon = item.icon
                const isActive = location.pathname === item.path || (item.path !== '/orders' && location.pathname.startsWith(item.path))
                return (
                  <Link
                    key={item.path}
                    to={item.path}
                    title={item.label}
                    className={`flex items-center gap-3 rounded-lg px-3.5 py-2.5 text-sm transition-all duration-150 md:justify-center md:px-2 xl:justify-start xl:px-3.5 ${
                      isActive
                        ? 'bg-white/20 text-white font-semibold shadow-sm backdrop-blur-sm'
                        : 'text-blue-100/80 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    <Icon className={`h-4 w-4 shrink-0 ${isActive ? 'text-white' : 'text-blue-200/80'}`} />
                    <span className="md:hidden xl:inline">{item.label}</span>
                  </Link>
                )
              })}
            </div>
          </section>
        ))}
      </nav>

      <div className="border-t border-white/15 bg-blue-950/20 p-4 md:p-2 xl:p-4">
        <div className="flex items-center gap-3 rounded-lg bg-white/10 p-2 md:justify-center xl:justify-start">
          <div className="rounded-full bg-white/20 p-2 text-white">
            {isAdmin ? <ShieldAlert className="h-4 w-4" /> : <UserCheck className="h-4 w-4" />}
          </div>
          <div className="min-w-0 overflow-hidden md:hidden xl:block">
            <p className="truncate text-xs font-semibold text-white">{user.full_name}</p>
            <span className="mt-0.5 inline-block rounded bg-white/20 px-2 py-0.5 font-mono text-[10px] font-semibold uppercase text-blue-100">
              {user.role}
            </span>
          </div>
        </div>
      </div>
    </aside>
  )
}
