import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth, ApiError } from '../auth/AuthContext'
import { PackageCheck, ShieldCheck, Lock, User, AlertCircle, ArrowRight } from 'lucide-react'

export function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!username || !password) return
    setError(null)
    setLoading(true)
    try {
      await login(username, password)
      navigate('/orders')
    } catch (err) {
      setError(err instanceof ApiError ? 'Sai tên đăng nhập hoặc mật khẩu' : 'Lỗi hệ thống hoặc kết nối máy chủ')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-[hsl(var(--tertiary))] flex items-center justify-center p-4 selection:bg-[#0052CC] selection:text-white">
      <div className="w-full max-w-md bg-white rounded-2xl border border-[hsl(var(--border))] shadow-xl overflow-hidden">
        {/* Header Gradient */}
        <div className="gradient-1 p-8 text-center text-white relative">
          <div className="inline-flex p-3 bg-white/20 rounded-2xl backdrop-blur-md mb-3 shadow-inner">
            <PackageCheck className="h-8 w-8 text-white" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">Tacahu Ops</h1>
          <p className="text-xs text-blue-100 mt-1 font-medium">Hệ Thống Điều Hành & Phân Đơn Nội Bộ V1</p>
        </div>

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="p-8 space-y-5">
          {error && (
            <div className="flex items-center gap-2.5 p-3.5 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs font-semibold">
              <AlertCircle className="h-4 w-4 shrink-0 text-red-600" />
              <span>{error}</span>
            </div>
          )}

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700 block">Tên Đăng Nhập</label>
            <div className="relative">
              <User className="h-4 w-4 absolute left-3.5 top-3 text-slate-400" />
              <input
                type="text"
                required
                className="w-full pl-10 pr-4 py-2.5 text-sm rounded-xl border border-slate-200 focus:outline-none focus:border-[#0052CC] focus:ring-2 focus:ring-[#0052CC]/20 bg-slate-50/50 font-medium transition-all"
                placeholder="Ví dụ: admin hoặc designer1"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-700 block">Mật Khẩu</label>
            <div className="relative">
              <Lock className="h-4 w-4 absolute left-3.5 top-3 text-slate-400" />
              <input
                type="password"
                required
                className="w-full pl-10 pr-4 py-2.5 text-sm rounded-xl border border-slate-200 focus:outline-none focus:border-[#0052CC] focus:ring-2 focus:ring-[#0052CC]/20 bg-slate-50/50 font-medium transition-all"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-3 px-4 rounded-xl bg-[#0052CC] hover:bg-[#0041A3] text-white font-semibold text-sm shadow-md hover:shadow-lg transition-all flex items-center justify-center gap-2 group disabled:opacity-50"
          >
            <span>{loading ? 'Đang xác thực...' : 'Đăng Nhập Hệ Thống'}</span>
            <ArrowRight className="h-4 w-4 group-hover:translate-x-0.5 transition-transform" />
          </button>

          <div className="pt-2 text-center text-xs text-slate-400 flex items-center justify-center gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-600" />
            <span>Bảo mật hệ thống nội bộ Enterprise</span>
          </div>
        </form>
      </div>
    </div>
  )
}
