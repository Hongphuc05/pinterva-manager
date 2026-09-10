import { useEffect, useState } from 'react'
import { DashboardLayout } from '../components/DashboardLayout'
import { apiFetch, ApiError } from '../api/client'
import { 
  Users, 
  UserPlus, 
  Trash2, 
  ShieldCheck, 
  User as UserIcon, 
  X, 
  Check, 
  AlertCircle,
  Loader2,
  Eye,
  KeyRound
} from 'lucide-react'

type UserItem = {
  id: string
  username: string
  full_name: string
  role: string
  active: boolean
  created_at: string
}

export function UsersPage() {
  const [users, setUsers] = useState<UserItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // Create User Form state
  const [showAddModal, setShowAddModal] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [fullName, setFullName] = useState('')
  const [role, setRole] = useState<'admin' | 'designer' | 'designer-trello'>('designer')
  const [submitting, setSubmitting] = useState(false)
  const [modalError, setModalError] = useState('')

  // Delete User Confirmation state
  const [deletingUser, setDeletingUser] = useState<UserItem | null>(null)
  const [deleting, setDeleting] = useState(false)

  const [passwordUser, setPasswordUser] = useState<UserItem | null>(null)
  const [revealedPassword, setRevealedPassword] = useState<string | null>(null)
  const [loadingPassword, setLoadingPassword] = useState(false)
  const [passwordError, setPasswordError] = useState('')
  const [changingPasswordUser, setChangingPasswordUser] = useState<UserItem | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [savingPassword, setSavingPassword] = useState(false)

  useEffect(() => {
    loadUsers()
  }, [])

  async function loadUsers() {
    setLoading(true)
    setError('')
    try {
      const data = await apiFetch<UserItem[]>('/users')
      setUsers(data)
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Không thể tải danh sách tài khoản.')
      }
    } finally {
      setLoading(false)
    }
  }

  async function handleCreateUser(e: React.FormEvent) {
    e.preventDefault()
    setModalError('')
    setSubmitting(true)
    try {
      await apiFetch<UserItem>('/users', {
        method: 'POST',
        body: JSON.stringify({
          username: username.trim(),
          password: password.trim(),
          full_name: fullName.trim() || username.trim(),
          role,
        }),
      })
      setShowAddModal(false)
      setUsername('')
      setPassword('')
      setFullName('')
      setRole('designer')
      loadUsers()
    } catch (err) {
      if (err instanceof ApiError) {
        setModalError(err.message)
      } else {
        setModalError('Lỗi khi tạo tài khoản mới.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  async function handleRevealPassword(user: UserItem) {
    setPasswordUser(user)
    setRevealedPassword(null)
    setPasswordError('')
    setLoadingPassword(true)
    try {
      const data = await apiFetch<{ password: string | null; recoverable: boolean }>(`/users/${user.id}/password`)
      if (data.recoverable && data.password) {
        setRevealedPassword(data.password)
      } else {
        setPasswordError('Mật khẩu của tài khoản cũ này chưa được lưu để xem. Hãy đổi mật khẩu một lần để lưu bản mã hóa.')
      }
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : 'Không thể xem mật khẩu.')
    } finally {
      setLoadingPassword(false)
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault()
    if (!changingPasswordUser) return
    setPasswordError('')
    setSavingPassword(true)
    try {
      await apiFetch<UserItem>(`/users/${changingPasswordUser.id}/password`, {
        method: 'PATCH',
        body: JSON.stringify({ password: newPassword }),
      })
      setChangingPasswordUser(null)
      setNewPassword('')
    } catch (err) {
      setPasswordError(err instanceof ApiError ? err.message : 'Không thể đổi mật khẩu.')
    } finally {
      setSavingPassword(false)
    }
  }

  async function handleDeleteUser() {
    if (!deletingUser) return
    setDeleting(true)
    try {
      await apiFetch(`/users/${deletingUser.id}`, { method: 'DELETE' })
      setDeletingUser(null)
      loadUsers()
    } catch (err) {
      if (err instanceof ApiError) {
        alert(`Không thể xóa: ${err.message}`)
      }
    } finally {
      setDeleting(false)
    }
  }

  return (
    <DashboardLayout>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-200">
          <div>
            <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
              <Users className="h-6 w-6 text-[#0052CC]" />
              <span>Quản Lý Tài Khoản</span>
            </h1>
            <p className="text-xs text-slate-500 mt-1">
              Tạo mới, phân quyền Admin, Designer và Designer Trello trong hệ thống
            </p>
          </div>

          <button
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center gap-2 px-4 py-2.5 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl transition-all shadow-md hover:shadow-lg cursor-pointer shrink-0"
          >
            <UserPlus className="h-4 w-4" />
            <span>Tạo Tài Khoản Mới</span>
          </button>
        </div>

        {error && (
          <div className="p-4 text-xs font-semibold text-red-700 bg-red-50 rounded-xl border border-red-200 flex items-center gap-2">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Users Table Card */}
        <div className="bg-white rounded-2xl border border-slate-200 shadow-2xs overflow-hidden">
          {loading ? (
            <div className="py-20 text-center text-slate-400 space-y-3">
              <Loader2 className="h-8 w-8 animate-spin mx-auto text-[#0052CC]" />
              <p className="text-xs font-medium">Đang tải danh sách tài khoản...</p>
            </div>
          ) : users.length === 0 ? (
            <div className="py-16 text-center text-slate-400 space-y-2">
              <Users className="h-10 w-10 mx-auto text-slate-300" />
              <p className="text-xs font-medium">Chưa có tài khoản nào khác trong hệ thống.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 text-slate-500 font-semibold uppercase text-[11px]">
                  <tr>
                    <th className="py-3.5 px-4">Tên Tài Khoản</th>
                    <th className="py-3.5 px-4">Họ Và Tên</th>
                    <th className="py-3.5 px-4">Vai Trò (Role)</th>
                    <th className="py-3.5 px-4">Trạng Thái</th>
                    <th className="py-3.5 px-4">Ngày Tạo</th>
                    <th className="py-3.5 px-4 text-right">Hành Động</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 font-medium">
                  {users.map((u) => {
                    const isAdmin = u.role === 'admin'
                    const isTrelloDesigner = u.role === 'designer-trello'
                    return (
                      <tr key={u.id} className="hover:bg-slate-50/70 transition-colors">
                        <td className="py-3.5 px-4 font-mono font-bold text-slate-800">
                          {u.username}
                        </td>
                        <td className="py-3.5 px-4 text-slate-700 font-semibold">
                          {u.full_name || u.username}
                        </td>
                        <td className="py-3.5 px-4">
                          {isAdmin ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-purple-50 text-purple-700 font-bold text-[11px] border border-purple-200">
                              <ShieldCheck className="h-3.5 w-3.5" />
                              <span>ADMIN</span>
                            </span>
                          ) : isTrelloDesigner ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-violet-50 text-violet-700 font-bold text-[11px] border border-violet-200">
                              <UserIcon className="h-3.5 w-3.5" />
                              <span>DESIGNER TRELLO</span>
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-700 font-bold text-[11px] border border-emerald-200">
                              <UserIcon className="h-3.5 w-3.5" />
                              <span>DESIGNER</span>
                            </span>
                          )}
                        </td>
                        <td className="py-3.5 px-4">
                          {u.active ? (
                            <span className="inline-flex items-center gap-1 text-emerald-600 font-semibold">
                              <Check className="h-3.5 w-3.5" />
                              <span>Hoạt động</span>
                            </span>
                          ) : (
                            <span className="text-slate-400">Đã khóa</span>
                          )}
                        </td>
                        <td className="py-3.5 px-4 text-slate-500 font-mono text-[11px]">
                          {new Date(u.created_at).toLocaleString('vi-VN')}
                        </td>
                        <td className="py-3.5 px-4 text-right">
                          <button
                            onClick={() => handleRevealPassword(u)}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-[#0052CC] hover:bg-blue-50 transition-colors cursor-pointer"
                            title="Xem mật khẩu"
                          >
                            <Eye className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => {
                              setChangingPasswordUser(u)
                              setNewPassword('')
                              setPasswordError('')
                            }}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-[#0052CC] hover:bg-blue-50 transition-colors cursor-pointer"
                            title="Đổi mật khẩu"
                          >
                            <KeyRound className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => setDeletingUser(u)}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-red-600 hover:bg-red-50 transition-colors cursor-pointer"
                            title="Xóa tài khoản"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Add User Modal */}
      {showAddModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
          onClick={() => setShowAddModal(false)}
        >
          <div
            className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col border border-slate-200"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50">
              <div className="flex items-center gap-2">
                <UserPlus className="h-5 w-5 text-[#0052CC]" />
                <h2 className="text-base font-bold text-slate-800">Tạo Tài Khoản Mới</h2>
              </div>
              <button
                onClick={() => setShowAddModal(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <form onSubmit={handleCreateUser} className="p-6 space-y-4">
              {modalError && (
                <div className="p-3 text-xs font-semibold text-red-700 bg-red-50 rounded-xl border border-red-200 flex items-center gap-2">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  <span>{modalError}</span>
                </div>
              )}

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Tên tài khoản (Username) <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="ví dụ: designer_linh"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">
                  Mật khẩu <span className="text-red-500">*</span>
                </label>
                <input
                  type="password"
                  required
                  placeholder="Nhập mật khẩu..."
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">Họ và Tên</label>
                <input
                  type="text"
                  placeholder="ví dụ: Nguyễn Thuý Hường"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">Vai Trò (Role)</label>
                <select
                  value={role}
                  onChange={(e) => setRole(e.target.value as 'admin' | 'designer' | 'designer-trello')}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 bg-white focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
                >
                  <option value="designer">Designer / Người dùng (Xử lý đơn hàng)</option>
                  <option value="designer-trello">Designer Trello / Xử lý đơn trùng lặp</option>
                  <option value="admin">Admin (Quản trị viên hệ thống)</option>
                </select>
              </div>

              <div className="pt-3 flex justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors cursor-pointer"
                >
                  Hủy
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl transition-colors shadow-2xs disabled:opacity-50 cursor-pointer"
                >
                  {submitting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  <span>{submitting ? 'Đang tạo...' : 'Tạo Tài Khoản'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* View password modal */}
      {passwordUser && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4"
          onClick={() => setPasswordUser(null)}
        >
          <div
            className="w-full max-w-md bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50">
              <div className="flex items-center gap-2">
                <Eye className="h-5 w-5 text-[#0052CC]" />
                <h2 className="text-base font-bold text-slate-800">Mật khẩu tài khoản</h2>
              </div>
              <button onClick={() => setPasswordUser(null)} className="p-1 rounded-lg text-slate-400 hover:bg-slate-200">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-xs text-slate-600">
                Tài khoản: <strong className="font-mono text-slate-900">{passwordUser.username}</strong>
              </p>
              {loadingPassword ? (
                <div className="py-5 text-center text-slate-500 text-xs">
                  <Loader2 className="h-5 w-5 animate-spin mx-auto mb-2 text-[#0052CC]" />
                  Đang tải mật khẩu...
                </div>
              ) : passwordError ? (
                <div className="p-3 text-xs leading-relaxed text-amber-800 bg-amber-50 border border-amber-200 rounded-xl">
                  {passwordError}
                </div>
              ) : (
                <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 font-mono text-sm text-slate-900 break-all select-all">
                  {revealedPassword}
                </div>
              )}
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => {
                    setPasswordUser(null)
                    setChangingPasswordUser(passwordUser)
                    setNewPassword('')
                    setPasswordError('')
                  }}
                  className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl"
                >
                  <KeyRound className="h-3.5 w-3.5" /> Đổi mật khẩu
                </button>
                <button onClick={() => setPasswordUser(null)} className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl">
                  Đóng
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Change password modal */}
      {changingPasswordUser && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4"
          onClick={() => setChangingPasswordUser(null)}
        >
          <form
            onSubmit={handleChangePassword}
            className="w-full max-w-md bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50">
              <div className="flex items-center gap-2">
                <KeyRound className="h-5 w-5 text-[#0052CC]" />
                <h2 className="text-base font-bold text-slate-800">Đổi mật khẩu</h2>
              </div>
              <button type="button" onClick={() => setChangingPasswordUser(null)} className="p-1 rounded-lg text-slate-400 hover:bg-slate-200">
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 space-y-4">
              <p className="text-xs text-slate-600">
                Đổi mật khẩu cho <strong className="font-mono text-slate-900">{changingPasswordUser.username}</strong>.
              </p>
              {passwordError && (
                <div className="p-3 text-xs text-red-700 bg-red-50 border border-red-200 rounded-xl">{passwordError}</div>
              )}
              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 block">Mật khẩu mới</label>
                <input
                  autoFocus
                  type="text"
                  minLength={4}
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full px-3.5 py-2 text-sm font-mono rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button type="button" onClick={() => setChangingPasswordUser(null)} className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl">
                  Hủy
                </button>
                <button type="submit" disabled={savingPassword} className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-xl disabled:opacity-50">
                  {savingPassword && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  Lưu mật khẩu
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* Delete User Confirmation Modal */}
      {deletingUser && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
          onClick={() => setDeletingUser(null)}
        >
          <div
            className="relative w-full max-w-sm bg-white rounded-2xl shadow-2xl p-6 space-y-4 border border-slate-200 text-center"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="h-12 w-12 rounded-full bg-red-100 text-red-600 flex items-center justify-center mx-auto">
              <Trash2 className="h-6 w-6" />
            </div>

            <div className="space-y-1">
              <h3 className="text-base font-bold text-slate-900">Xác Nhận Xóa Tài Khoản</h3>
              <p className="text-xs text-slate-500">
                Bạn có chắc chắn muốn xóa tài khoản <strong className="text-slate-800">{deletingUser.username}</strong> ({deletingUser.full_name})? Hành động này không thể hoàn tác.
              </p>
            </div>

            <div className="flex justify-center gap-2 pt-2">
              <button
                onClick={() => setDeletingUser(null)}
                className="px-4 py-2 text-xs font-bold text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-xl transition-colors cursor-pointer"
              >
                Hủy
              </button>
              <button
                onClick={handleDeleteUser}
                disabled={deleting}
                className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold text-white bg-red-600 hover:bg-red-700 rounded-xl transition-colors shadow-2xs disabled:opacity-50 cursor-pointer"
              >
                {deleting && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                <span>{deleting ? 'Đang xóa...' : 'Xóa Ngay'}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  )
}
