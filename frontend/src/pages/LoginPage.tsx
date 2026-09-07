import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth, ApiError } from '../auth/AuthContext'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await login(username, password)
      navigate('/orders')
    } catch (err) {
      setError(err instanceof ApiError ? 'Sai tên đăng nhập hoặc mật khẩu' : 'Lỗi kết nối')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="max-w-sm mx-auto mt-20 p-6 space-y-4">
      <h1 className="text-xl font-bold">Đăng nhập</h1>
      {error && <p className="text-red-600">{error}</p>}
      <input
        className="border w-full p-2"
        placeholder="Tên đăng nhập"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
      />
      <input
        className="border w-full p-2"
        type="password"
        placeholder="Mật khẩu"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <button className="bg-blue-600 text-white w-full p-2" type="submit">
        Đăng nhập
      </button>
    </form>
  )
}
