import { Navigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './AuthContext'

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="p-6">Đang tải...</div>
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}
