import React, { useState } from 'react'
import { usePlatform } from '../auth/PlatformContext'
import { useAuth } from '../auth/AuthContext'

export const PlatformSwitcher: React.FC = () => {
  const { isAdmin } = useAuth()
  const { platforms, activePlatform, setActivePlatform, createPlatform } = usePlatform()

  const [isModalOpen, setIsModalOpen] = useState(false)
  const [name, setName] = useState('')
  const [accountUsername, setAccountUsername] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  if (!isAdmin) return null

  return (
    <div className="flex items-center gap-2">
      <div className="flex items-center gap-1.5 bg-blue-50 text-[#0052CC] border border-blue-200 px-3 py-1.5 rounded-xl font-semibold text-xs shadow-2xs">
        <span className="text-sm">🔑</span>
        <select
          value={activePlatform?.id || ''}
          onChange={(e) => {
            const selected = platforms.find((p) => p.id === e.target.value)
            if (selected) setActivePlatform(selected)
          }}
          className="bg-transparent text-[#0052CC] font-bold text-xs outline-none cursor-pointer"
        >
          {platforms.map((p) => (
            <option key={p.id} value={p.id} className="text-slate-800 bg-white">
              {p.name} ({p.account_username})
            </option>
          ))}
        </select>
      </div>

      <button
        onClick={() => setIsModalOpen(true)}
        className="px-3 py-1.5 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl shadow-2xs transition-colors cursor-pointer"
        title="Thêm nền tảng / acc mẹ Printerval mới"
      >
        + Thêm Acc Mẹ
      </button>

      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200">
          <div className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl p-6 border border-slate-200 text-slate-800">
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-base font-bold text-slate-900">Thêm Nền Tảng (Acc Mẹ Printerval)</h3>
              <button
                onClick={() => setIsModalOpen(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors"
              >
                ✕
              </button>
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-800 p-3 rounded-xl mb-4 text-xs font-medium">
                {error}
              </div>
            )}

            <form
              onSubmit={async (e) => {
                e.preventDefault()
                if (!name.trim() || !accountUsername.trim()) {
                  setError('Vui lòng điền đầy đủ Tên nền tảng và Email/Username acc mẹ.')
                  return
                }
                setSubmitting(true)
                setError(null)
                try {
                  await createPlatform(name.trim(), accountUsername.trim())
                  setIsModalOpen(false)
                  setName('')
                  setAccountUsername('')
                } catch (err: any) {
                  setError(err.message || 'Không thể tạo nền tảng mới.')
                } finally {
                  setSubmitting(false)
                }
              }}
              className="space-y-4 text-xs"
            >
              <div>
                <label className="block font-bold text-slate-700 mb-1">
                  Tên Nền Tảng / Cửa Hàng <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  placeholder="ví dụ: Acc Mẹ Printerval 2 (Store US)"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full px-3.5 py-2 rounded-xl border border-slate-300 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
                  required
                />
              </div>

              <div>
                <label className="block font-bold text-slate-700 mb-1">
                  Email / Username Đăng Nhập Acc Mẹ <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  placeholder="ví dụ: seller_us_02@printerval.com"
                  value={accountUsername}
                  onChange={(e) => setAccountUsername(e.target.value)}
                  className="w-full px-3.5 py-2 rounded-xl border border-slate-300 bg-white text-slate-800 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
                  required
                />
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 rounded-xl border border-slate-300 bg-slate-100 hover:bg-slate-200 text-slate-700 font-bold transition-colors cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-4 py-2 rounded-xl border border-transparent bg-emerald-600 hover:bg-emerald-700 text-white font-bold transition-colors shadow-2xs disabled:opacity-50 cursor-pointer"
                >
                  {submitting ? 'Đang tạo...' : 'Tạo Nền Tảng Mới'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
