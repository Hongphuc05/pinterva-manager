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
  Columns3
} from 'lucide-react'

export function Sidebar() {
  const { user } = useAuth()
  const location = useLocation()

  if (!user) return null

  const isAdmin = user.role === 'admin'
  const isTrelloDesigner = user.role === 'designer-trello'

  const adminSections = [
    {
      label: 'Vận hành',
      items: [
        { label: 'Đơn Hàng', path: '/orders', icon: ListOrdered },
        { label: 'Tiến Độ Team', path: '/designer-board', icon: UserCheck },
        { label: 'Board Đơn trùng lặp', path: '/kanban', icon: Columns3 },
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

  const designerSections = [
    {
      label: 'Công việc',
      items: [
        { label: 'Nhiệm Vụ Của Tôi', path: '/orders', icon: ListOrdered },
        { label: 'Lịch Sử Của Tôi', path: '/order-history', icon: History },
        { label: 'Tài Chính Của Tôi', path: '/finance', icon: Coins },
      ],
    },
  ]

  const trelloDesignerSections = [
    {
      label: 'Đơn trùng lặp',
      items: [
        { label: 'Board kéo thả', path: '/kanban', icon: Columns3 },
      ],
    },
  ]

  const navSections = isAdmin ? adminSections : isTrelloDesigner ? trelloDesignerSections : designerSections

  return (
    <aside className="w-64 bg-[#0052CC] text-white flex flex-col fixed lg:sticky top-0 h-screen z-50 shadow-lg select-none">
      {/* Brand Header */}
      <div className="h-16 flex items-center gap-3 px-6 border-b border-white/15 bg-blue-900/30">
        <div className="p-2 bg-white/20 rounded-xl backdrop-blur-md">
          <PackageCheck className="h-6 w-6 text-white" />
        </div>
        <div>
          <h1 className="font-bold text-base tracking-tight text-white leading-none">Tacahu Ops</h1>
          <p className="text-[11px] text-blue-100/70 mt-1 font-medium">System Dashboard V1</p>
        </div>
      </div>

      {/* Navigation Items */}
      <div className="flex-1 py-6 px-3 space-y-1 overflow-y-auto">
        {navSections.map((section) => (
          <section key={section.label} className="mb-5 last:mb-0">
            <div className="px-3 pb-2 text-[11px] font-semibold text-blue-200/60 uppercase tracking-wider">
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
                    className={`flex items-center gap-3 px-3.5 py-2.5 rounded-lg text-sm transition-all duration-150 ${
                      isActive
                        ? 'bg-white/20 text-white font-semibold shadow-sm backdrop-blur-sm'
                        : 'text-blue-100/80 hover:bg-white/10 hover:text-white'
                    }`}
                  >
                    <Icon className={`h-4 w-4 ${isActive ? 'text-white' : 'text-blue-200/80'}`} />
                    <span>{item.label}</span>
                  </Link>
                )
              })}
            </div>
          </section>
        ))}
      </div>

      {/* User Info Footer */}
      <div className="p-4 border-t border-white/15 bg-blue-950/20">
        <div className="flex items-center gap-3 p-2 rounded-lg bg-white/10">
          <div className="p-2 rounded-full bg-white/20 text-white">
            {isAdmin ? <ShieldAlert className="h-4 w-4" /> : <UserCheck className="h-4 w-4" />}
          </div>
          <div className="overflow-hidden">
            <p className="text-xs font-semibold text-white truncate">{user.full_name}</p>
            <span className="inline-block mt-0.5 px-2 py-0.5 text-[10px] font-mono font-semibold rounded bg-white/20 text-blue-100 uppercase">
              {user.role}
            </span>
          </div>
        </div>
      </div>
    </aside>
  )
}
