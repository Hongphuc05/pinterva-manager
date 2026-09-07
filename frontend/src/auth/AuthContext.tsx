import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { apiFetch, ApiError } from '../api/client'

export type User = { id: string; role: 'admin' | 'designer'; full_name: string }

type AuthState = {
  user: User | null
  loading: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiFetch<User>('/me')
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])

  async function login(username: string, password: string) {
    await apiFetch('/login', { method: 'POST', body: JSON.stringify({ username, password }) })
    const me = await apiFetch<User>('/me')
    setUser(me)
  }

  async function logout() {
    await apiFetch('/logout', { method: 'POST' })
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
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
