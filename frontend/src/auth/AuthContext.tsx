import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { apiFetch, ApiError } from '../api/client'

export type User = {
  id: string
  username: string
  role: 'admin' | 'designer' | string
  full_name: string
}

type AuthState = {
  user: User | null
  loading: boolean
  isAdmin: boolean
  login: (username: string, password: string) => Promise<User>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiFetch<User>('/me')
      .then(setUser)
      .catch(() => {
        localStorage.removeItem('token')
        setUser(null)
      })
      .finally(() => setLoading(false))
  }, [])

  async function login(username: string, password: string): Promise<User> {
    const res = await apiFetch<{
      access_token?: string
      user?: User
      id: string
      role: string
    }>('/login', { method: 'POST', body: JSON.stringify({ username, password }) })

    if (res.access_token) {
      localStorage.setItem('token', res.access_token)
    }

    const me = await apiFetch<User>('/me')
    setUser(me)
    return me
  }

  async function logout() {
    try {
      await apiFetch('/logout', { method: 'POST' })
    } catch {
      // ignore logout fetch errors
    } finally {
      localStorage.removeItem('token')
      setUser(null)
    }
  }

  const isAdmin = user?.role === 'admin'

  return (
    <AuthContext.Provider value={{ user, loading, isAdmin, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export { ApiError }
