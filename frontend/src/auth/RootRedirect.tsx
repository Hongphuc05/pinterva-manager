import { Navigate } from 'react-router-dom'
import { useAuth } from './AuthContext'

/** "/" goes to each role's home page — not always Orders (Designer Trello: Kanban, Accountant: Payments). */
export function RootRedirect() {
  const { user, loading } = useAuth()
  if (loading) return <div className="p-6">Đang tải...</div>
  if (!user) return <Navigate to="/login" replace />
  const home = user.role === 'designer-trello' ? '/kanban' : user.role === 'accountant' ? '/payments' : '/orders'
  return <Navigate to={home} replace />
}
