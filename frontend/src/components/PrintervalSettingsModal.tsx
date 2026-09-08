import { useState } from 'react'
import { X, KeyRound, Check, AlertCircle, Loader2, ArrowRightLeft, Plus, CheckCircle2 } from 'lucide-react'
import { apiFetch, ApiError } from '../api/client'
import { usePlatform } from '../auth/PlatformContext'

type PrintervalSettingsModalProps = {
  isOpen: boolean
  onClose: () => void
}

export function PrintervalSettingsModal({ isOpen, onClose }: PrintervalSettingsModalProps) {
  const { platforms, activePlatform, setActivePlatform, refreshPlatforms } = usePlatform()
  const [activeTab, setActiveTab] = useState<'switch' | 'new'>('switch')

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [teamOutsource, setTeamOutsource] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')

  if (!isOpen) return null

  async function handleLoginNewAccount(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || !password.trim() || !teamOutsource.trim()) {
      setError('Vui lòng nhập đầy đủ tên tài khoản, mật khẩu và Team Outsource của Printerval!')
      return
    }
    setError('')
    setSuccessMsg('')
    setLoading(true)

    try {
      const res = await apiFetch<{
        ok: boolean
        platform_id: string
        platform_name: string
        account_username: string
        message: string
      }>('/orders/printerval-credentials', {
        method: 'POST',
        body: JSON.stringify({
          username: username.trim(),
          password: password.trim(),
          team_outsource: teamOutsource.trim(),
        }),
      })

      setSuccessMsg(res.message || 'Đã đăng nhập tài khoản Printerval mới thành công!')
      await refreshPlatforms()

      // Set active platform to the newly logged in account
      if (res.platform_id) {
        localStorage.setItem('activePlatformId', res.platform_id)
      }

      setTimeout(() => {
        window.location.reload()
      }, 1000)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Có lỗi xảy ra khi đăng nhập tài khoản Printerval mới.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col border border-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50">
          <div className="flex items-center gap-2">
            <KeyRound className="h-5 w-5 text-[#0052CC]" />
            <div>
              <h2 className="text-base font-bold text-slate-800">Quản Lý Workspace Acc Mẹ Printerval</h2>
              {activePlatform && (
                <p className="text-[11px] text-slate-500 font-medium">
                  Đang chọn: <span className="font-bold text-[#0052CC]">{activePlatform.account_username}</span>
                </p>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Tab Navigation */}
        <div className="flex border-b border-slate-100 bg-slate-50/50 px-6 pt-2 gap-2 text-xs font-semibold">
          <button
            onClick={() => setActiveTab('switch')}
            className={`pb-2.5 px-3 flex items-center gap-1.5 border-b-2 transition-all cursor-pointer ${
              activeTab === 'switch'
                ? 'border-[#0052CC] text-[#0052CC] font-bold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <ArrowRightLeft className="h-3.5 w-3.5" />
            <span>Đổi Acc Mẹ ({platforms.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('new')}
            className={`pb-2.5 px-3 flex items-center gap-1.5 border-b-2 transition-all cursor-pointer ${
              activeTab === 'new'
                ? 'border-[#0052CC] text-[#0052CC] font-bold'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            }`}
          >
            <Plus className="h-3.5 w-3.5" />
            <span>Đăng Nhập Acc Mẹ Mới</span>
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
          {error && (
            <div className="p-3 text-xs font-semibold text-red-700 bg-red-50 rounded-xl border border-red-200 flex items-center gap-2">
              <AlertCircle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {successMsg && (
            <div className="p-3 text-xs font-semibold text-emerald-700 bg-emerald-50 rounded-xl border border-emerald-200 flex items-center gap-2">
              <Check className="h-4 w-4 shrink-0" />
              <span>{successMsg}</span>
            </div>
          )}

          {/* TAB 1: SWITCH ACC MẸ */}
          {activeTab === 'switch' && (
            <div className="space-y-3">
              <p className="text-xs text-slate-500 font-medium">
                Chọn một tài khoản mẹ Printerval bên dưới để chuyển workspace. Mỗi tài khoản mẹ chứa toàn bộ dữ liệu đơn hàng, phân công và cài đặt biệt lập hoàn toàn.
              </p>

              <div className="space-y-2">
                {platforms.map((p) => {
                  const isCurrent = activePlatform?.id === p.id
                  return (
                    <div
                      key={p.id}
                      className={`p-3.5 rounded-xl border flex items-center justify-between transition-all ${
                        isCurrent
                          ? 'bg-blue-50/70 border-blue-200 shadow-2xs'
                          : 'bg-white border-slate-200 hover:bg-slate-50'
                      }`}
                    >
                      <div className="space-y-0.5 text-xs">
                        <div className="font-bold text-slate-800 flex items-center gap-1.5">
                          <span>{p.name}</span>
                          {isCurrent && (
                            <span className="inline-flex items-center gap-1 text-[10px] bg-blue-600 text-white font-bold px-2 py-0.5 rounded-full">
                              <CheckCircle2 className="h-3 w-3" /> Đang dùng
                            </span>
                          )}
                        </div>
                        <p className="font-mono text-slate-500 text-[11px]">{p.account_username}</p>
                      </div>

                      {!isCurrent && (
                        <button
                          onClick={() => setActivePlatform(p)}
                          className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-lg transition-colors cursor-pointer shadow-2xs"
                        >
                          <span>Chuyển sang Acc này</span>
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>

              <div className="pt-2 text-center">
                <button
                  onClick={() => setActiveTab('new')}
                  className="text-xs font-bold text-[#0052CC] hover:underline cursor-pointer inline-flex items-center gap-1"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span>Đăng nhập thêm Acc Mẹ khác</span>
                </button>
              </div>
            </div>
          )}

          {/* TAB 2: REGISTER NEW ACC MẸ */}
          {activeTab === 'new' && (
            <form onSubmit={handleLoginNewAccount} className="space-y-4">
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900 space-y-1">
                <p className="font-bold">🔑 Đăng nhập Acc Mẹ Printerval Mới</p>
                <p className="text-[11px] text-amber-800">
                  Khi đăng nhập tài khoản mẹ mới, hệ thống sẽ tự động tạo một Workspace riêng biệt cho tài khoản này trong CSDL.
                </p>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Email / Username Acc Mẹ Printerval <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="ví dụ: seller_us_02@printerval.com"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] transition-all"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Mật khẩu Printerval <span className="text-red-500">*</span>
                </label>
                <input
                  type="password"
                  required
                  placeholder="Nhập mật khẩu..."
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] transition-all"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Team Outsource <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="ví dụ: 2D Prin"
                  value={teamOutsource}
                  onChange={(e) => setTeamOutsource(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] transition-all"
                />
                <p className="text-[10px] text-slate-400">
                  Bắt buộc — mỗi tài khoản mẹ Printerval chỉ quét được đúng team này. Lấy từ Network request thật khi đăng nhập account đó.
                </p>
              </div>

              <div className="pt-3 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={loading}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 rounded-xl transition-colors shadow-2xs disabled:opacity-50 cursor-pointer"
                >
                  {loading && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>{loading ? 'Đang đăng nhập...' : 'Đăng Nhập & Chuyển Workspace'}</span>
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
