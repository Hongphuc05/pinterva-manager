import { useState } from 'react'
import { X, KeyRound, Check, AlertCircle, Loader2, ArrowRightLeft, Plus, CheckCircle2, HelpCircle, Copy } from 'lucide-react'
import { apiFetch } from '../api/client'
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
  const [sessionCookie, setSessionCookie] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')
  const [showTeamOutsourceHelp, setShowTeamOutsourceHelp] = useState(false)
  const [showCookieHelp, setShowCookieHelp] = useState(false)
  const [galleryBridgeToken, setGalleryBridgeToken] = useState('')
  const [creatingGalleryBridgeToken, setCreatingGalleryBridgeToken] = useState(false)

  if (!isOpen) return null

  async function handleLoginNewAccount(e: React.FormEvent) {
    e.preventDefault()
    if (!username.trim() || !teamOutsource.trim()) {
      setError('Vui lòng nhập đầy đủ Email / Username và Team Outsource của Printerval!')
      return
    }
    if (!password.trim() && !sessionCookie.trim()) {
      setError('Vui lòng nhập Mật khẩu HOẶC Session Cookie Printerval (laravel_session)!')
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
          password: password.trim() || undefined,
          team_outsource: teamOutsource.trim(),
          session_cookie: sessionCookie.trim() || undefined,
        }),
      })

      setSuccessMsg(res.message || 'Đã cập nhật / đăng nhập tài khoản Printerval thành công!')
      await refreshPlatforms()

      // Set active platform to the newly logged in account
      if (res.platform_id) {
        localStorage.setItem('activePlatformId', res.platform_id)
      }

      setTimeout(() => {
        window.location.reload()
      }, 1000)
    } catch (err: any) {
      setError(err?.message || 'Có lỗi xảy ra khi đăng nhập / cập nhật tài khoản Printerval.')
    } finally {
      setLoading(false)
    }
  }

  async function createGalleryBridgeToken() {
    if (!activePlatform) return
    setCreatingGalleryBridgeToken(true)
    setError('')
    try {
      const result = await apiFetch<{ token: string; message: string }>(
        `/platforms/${activePlatform.id}/gallery-bridge-token`,
        { method: 'POST' },
      )
      setGalleryBridgeToken(result.token)
      setSuccessMsg(result.message)
    } catch (err: any) {
      setError(err?.message || 'Không tạo được token CopyImage.')
    } finally {
      setCreatingGalleryBridgeToken(false)
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
            <span>Cập Nhật / Đăng Nhập Acc Mẹ</span>
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-4 max-h-[75vh] overflow-y-auto">
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
                Chọn một tài khoản mẹ Printerval bên dưới để chuyển workspace hoặc bấm "Cập nhật Cookie" nếu tài khoản bị hết hạn đăng nhập.
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
                        {p.team_outsource && (
                          <p className="text-[10px] text-slate-400">Team Outsource: <span className="font-semibold text-slate-600">{p.team_outsource}</span></p>
                        )}
                      </div>

                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => {
                            setUsername(p.account_username)
                            setTeamOutsource(p.team_outsource || '')
                            setSessionCookie(p.session_cookie || '')
                            setActiveTab('new')
                          }}
                          className="px-2.5 py-1.5 text-[11px] font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors cursor-pointer border border-slate-200"
                          title="Cập nhật Session Cookie hoặc Mật khẩu"
                        >
                          Cập nhật Cookie
                        </button>

                        {!isCurrent && (
                          <button
                            onClick={() => setActivePlatform(p)}
                            className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-bold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-lg transition-colors cursor-pointer shadow-2xs"
                          >
                            <span>Chuyển Acc</span>
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>

              {activePlatform && (
                <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 space-y-2">
                  <p className="text-xs font-bold text-slate-700">Kết nối extension CopyImage</p>
                  <p className="text-[11px] text-slate-500">
                    Tạo token riêng cho platform đang chọn rồi dán vào Cài đặt CopyImage. Token chỉ đồng bộ gallery cho platform này.
                  </p>
                  <div className="flex items-center gap-2">
                    <code className="min-w-0 flex-1 truncate rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px]" title={activePlatform.id}>
                      Platform ID: {activePlatform.id}
                    </code>
                    <button
                      type="button"
                      onClick={() => navigator.clipboard.writeText(activePlatform.id)}
                      className="p-2 rounded-lg border border-slate-200 bg-white text-slate-600 hover:text-[#0052CC]"
                      title="Sao chép Platform ID"
                    >
                      <Copy className="h-3.5 w-3.5" />
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={createGalleryBridgeToken}
                    disabled={creatingGalleryBridgeToken}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-[#0052CC] hover:bg-[#0041A3] rounded-lg disabled:opacity-60"
                  >
                    {creatingGalleryBridgeToken && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                    {galleryBridgeToken ? 'Tạo token mới' : 'Tạo token CopyImage'}
                  </button>
                  {galleryBridgeToken && (
                    <div className="flex gap-2">
                      <code className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-[10px] break-all">{galleryBridgeToken}</code>
                      <button type="button" onClick={() => navigator.clipboard.writeText(galleryBridgeToken)} className="p-2 rounded-lg border border-slate-200 bg-white text-slate-600 hover:text-[#0052CC]" title="Sao chép token">
                        <Copy className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  )}
                </div>
              )}

              <div className="pt-2 text-center">
                <button
                  onClick={() => {
                    setUsername('')
                    setPassword('')
                    setTeamOutsource('')
                    setSessionCookie('')
                    setActiveTab('new')
                  }}
                  className="text-xs font-bold text-[#0052CC] hover:underline cursor-pointer inline-flex items-center gap-1"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span>Đăng nhập thêm Acc Mẹ khác</span>
                </button>
              </div>
            </div>
          )}

          {/* TAB 2: REGISTER / UPDATE ACC MẸ */}
          {activeTab === 'new' && (
            <form onSubmit={handleLoginNewAccount} className="space-y-4">
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-xs text-amber-900 space-y-1">
                <p className="font-bold">Cập Nhật / Đăng Nhập Acc Mẹ Printerval</p>
                <p className="text-[11px] text-amber-800">
                  Nhập Session Cookie Printerval (laravel_session) thu thập từ F12 DevTools để hệ thống crawl đơn nhanh chóng & bỏ qua Cloudflare WAF.
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
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] transition-all font-mono"
                />
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-slate-700 flex items-center justify-between">
                  <span>Mật khẩu Printerval</span>
                  <span className="text-[10px] text-slate-400 font-normal">(Không bắt buộc nếu đã nhập Session Cookie)</span>
                </label>
                <input
                  type="password"
                  placeholder="Nhập mật khẩu (tùy chọn)..."
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-3.5 py-2 text-xs rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] transition-all"
                />
              </div>

              <div className="space-y-1 relative">
                <label className="text-xs font-bold text-slate-700 flex items-center gap-1">
                  <span>Team Outsource</span>
                  <button
                    type="button"
                    onClick={() => setShowTeamOutsourceHelp((v) => !v)}
                    className="text-red-500 hover:text-[#0052CC] cursor-pointer inline-flex items-center"
                    title="Xem hướng dẫn lấy Team Outsource"
                  >
                    *
                  </button>
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
                  Bắt buộc — mỗi tài khoản mẹ Printerval chỉ quét được đúng team này.{' '}
                  <button
                    type="button"
                    onClick={() => setShowTeamOutsourceHelp((v) => !v)}
                    className="text-[#0052CC] font-semibold underline cursor-pointer"
                  >
                    Cách lấy giá trị này?
                  </button>
                </p>

                {showTeamOutsourceHelp && (
                  <div className="absolute z-20 top-full mt-1 left-0 right-0 p-3 bg-slate-800 text-slate-100 rounded-xl shadow-xl text-[11px] space-y-1.5 border border-slate-700">
                    <div className="flex items-center justify-between">
                      <p className="font-bold flex items-center gap-1 text-amber-400">
                        <HelpCircle className="h-3.5 w-3.5" />
                        Cách lấy Team Outsource
                      </p>
                      <button
                        type="button"
                        onClick={() => setShowTeamOutsourceHelp(false)}
                        className="text-slate-400 hover:text-white cursor-pointer"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <ol className="list-decimal list-inside space-y-1 text-slate-200">
                      <li>Đăng nhập trực tiếp trên trình duyệt vào printerval.com bằng tài khoản mẹ.</li>
                      <li>Vào trang: <code className="bg-slate-700 px-1 rounded text-cyan-300">printerval.com/central/outsource/pod/design-job/admin</code></li>
                      <li>Mở DevTools (F12) → tab Network → F5 tải lại trang.</li>
                      <li>Tìm dòng request có tên dạng: <code className="bg-slate-700 px-1 rounded text-amber-300">count?team_outsource=...</code></li>
                      <li>Giá trị ngay sau <code className="bg-slate-700 px-1 rounded">team_outsource=</code> chính là giá trị cần điền.</li>
                    </ol>
                  </div>
                )}
              </div>

              {/* Session Cookie Input Field */}
              <div className="space-y-1 relative">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-bold text-slate-700 flex items-center gap-1.5">
                    <span>Session Cookie Printerval</span>
                    <span className="text-[10px] text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded-full border border-emerald-200 font-semibold">
                      Khuyên dùng trên Cloud
                    </span>
                  </label>
                  <button
                    type="button"
                    onClick={() => setShowCookieHelp((v) => !v)}
                    className="text-[#0052CC] hover:underline text-xs font-semibold cursor-pointer inline-flex items-center gap-1"
                  >
                    <HelpCircle className="h-3.5 w-3.5" />
                    <span>Cách lấy Cookie?</span>
                  </button>
                </div>
                <textarea
                  rows={3}
                  placeholder="Dán laravel_session=eyJ... hoặc toàn bộ chuỗi Cookie từ DevTools vào đây"
                  value={sessionCookie}
                  onChange={(e) => {
                    let cleaned = e.target.value
                    if (cleaned.toLowerCase().startsWith('cookie:')) {
                      cleaned = cleaned.slice(7).trim()
                    }
                    setSessionCookie(cleaned)
                  }}
                  className="w-full px-3.5 py-2 text-xs font-mono rounded-xl border border-slate-300 focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC] transition-all bg-slate-50/50"
                />
                {(() => {
                  if (!sessionCookie.trim()) return false
                  let val = sessionCookie.trim()
                  if (val.toLowerCase().startsWith('cookie:')) val = val.slice(7).trim()
                  const match = val.match(/(?:^|;\s*)laravel_session=([^;]+)/)
                  if (match) val = match[1].trim()
                  else if (val.startsWith('laravel_session=')) val = val.slice('laravel_session='.length).trim()
                  val = val.replace(/^["']|["']$/g, '')
                  return !val.startsWith('eyJ') && !val.startsWith('%7B')
                })() && (
                  <p className="text-[11px] font-semibold text-amber-800 bg-amber-50 p-2.5 rounded-xl border border-amber-300 flex items-start gap-1.5">
                    <AlertCircle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                    <span>
                      <strong>Chú ý:</strong> Chuỗi Cookie bạn vừa dán có vẻ bị thiếu phần đầu hoặc bị cắt ngắn (chuỗi hiện tại bắt đầu bằng <code className="font-mono text-amber-950 bg-amber-200/80 px-1 rounded">{sessionCookie.trim().slice(0, 15)}...</code>, trong khi chuẩn phải bắt đầu bằng <code className="font-mono text-amber-950 bg-amber-200/80 px-1 rounded">eyJpdi...</code> hoặc <code className="font-mono text-amber-950 bg-amber-200/80 px-1 rounded">laravel_session=eyJpdi...</code>). Hãy bôi đen copy lại toàn bộ giá trị trong DevTools.
                    </span>
                  </p>
                )}
                <p className="text-[10px] text-slate-400">
                  Khuyên dùng khi deploy web trên Render / Vercel / VPS để không bị Cloudflare WAF chặn.
                </p>

                {showCookieHelp && (
                  <div className="absolute z-20 top-full mt-1 left-0 right-0 p-3.5 bg-slate-900 text-slate-100 rounded-xl shadow-xl text-[11px] space-y-2 border border-slate-700 animate-in fade-in duration-150">
                    <div className="flex items-center justify-between border-b border-slate-700 pb-1.5">
                      <p className="font-bold text-amber-400 flex items-center gap-1.5">
                        <HelpCircle className="h-4 w-4" />
                        Hướng dẫn lấy Session Cookie (laravel_session)
                      </p>
                      <button
                        type="button"
                        onClick={() => setShowCookieHelp(false)}
                        className="text-slate-400 hover:text-white cursor-pointer"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                    <ol className="list-decimal list-inside space-y-1.5 text-slate-200">
                      <li>Đăng nhập trực tiếp trên trình duyệt vào <b>printerval.com</b> bằng tài khoản mẹ này.</li>
                      <li>Vào trang: <code className="bg-slate-800 text-emerald-300 px-1 py-0.5 rounded font-mono text-[10px]">printerval.com/central/outsource/pod/design-job/admin</code></li>
                      <li>Nhấn <b>F12</b> (mở DevTools) → Chọn tab <b>Network</b>.</li>
                      <li>Nhấn <b>F5</b> để tải lại trang.</li>
                      <li>Tìm dòng request có tên: <code className="bg-slate-800 text-amber-300 px-1 py-0.5 rounded font-mono text-[10px]">count?team_outsource=...</code> (hoặc <code className="bg-slate-800 text-amber-300 px-1 py-0.5 rounded font-mono text-[10px]">find</code>).</li>
                      <li>Click vào dòng request đó → Chọn tab <b>Headers</b> → Mục <b>Request Headers</b>.</li>
                      <li>Tìm thuộc tính <b>Cookie</b>, copy chuỗi <code className="bg-slate-800 text-cyan-300 px-1 py-0.5 rounded font-mono text-[10px]">laravel_session=...</code> (hoặc toàn bộ chuỗi Cookie) và dán vào ô trên.</li>
                    </ol>
                  </div>
                )}
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
                  <span>{loading ? 'Đang xác thực...' : 'Lưu & Kích Hoạt Workspace'}</span>
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
