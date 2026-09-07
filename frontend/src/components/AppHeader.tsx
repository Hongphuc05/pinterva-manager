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
        Pinterval Ops
      </Link>
      <div className="flex items-center gap-4 text-sm">
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
