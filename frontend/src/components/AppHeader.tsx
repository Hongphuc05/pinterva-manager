import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'

export function AppHeader() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  if (!user) return null

  return (
    <header className="flex justify-between items-center p-4 border-b bg-gray-50">
      <Link to="/orders" className="font-bold">
        Tacahu Ops
      </Link>
      <div className="flex items-center gap-4 text-sm">
        {user.role === 'admin' && (
          <Link to="/allocation" className="underline">
            Phân bổ
          </Link>
        )}
        {user.role === 'admin' && <Link to="/kanban" className="underline">Kanban</Link>}
        {user.role === 'designer' && (
          <Link to="/my-tasks" className="underline">
            Task của tôi
          </Link>
        )}
        <span>
          {user.full_name} ({user.role})
        </span>
        <button onClick={handleLogout} className="underline">
          Đăng xuất
        </button>
      </div>
    </header>
  )
}
