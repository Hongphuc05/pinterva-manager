import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { usePlatform } from '../auth/PlatformContext'
import { apiFetch } from '../api/client'
import { Bell, LogOut, RefreshCw, CheckCircle2, AlertCircle, X, KeyRound } from 'lucide-react'
import { PrintervalSettingsModal } from './PrintervalSettingsModal'
import { CrawlFilterModal } from './CrawlFilterModal'

export function Topbar() {
  const { user, logout } = useAuth()
  const { activePlatform } = usePlatform()
  const navigate = useNavigate()
  const location = useLocation()
  const [refreshing, setRefreshing] = useState(false)
  const [flashMessage, setFlashMessage] = useState<string | null>(null)
  const [isError, setIsError] = useState(false)
  const [showSettingsModal, setShowSettingsModal] = useState(false)
  const [showCrawlModal, setShowCrawlModal] = useState(false)

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  function getPageTitle(path: string) {
    if (path.startsWith('/orders/')) return 'Chi Tiết Đơn Hàng'
    if (path === '/orders') return 'Danh Sách Đơn Hàng'
    if (path === '/allocation') return 'Phân Bổ Kéo-Thả'
    if (path === '/kanban') return 'Bảng Tiến Độ Kanban'
    if (path === '/my-tasks') return 'Task Của Tôi'
    if (path === '/printerval-login') return 'Đăng Nhập Printerval'
    return 'Dashboard'
  }

  // Auto-dismiss toast notification popup after 7 seconds (7000ms)
  useEffect(() => {
    if (!flashMessage) return
    const timer = setTimeout(() => {
      setFlashMessage(null)
    }, 7000)
    return () => clearTimeout(timer)
  }, [flashMessage])

  async function handleRefreshCrawl(jobType: string, dateFrom: string, dateTo: string) {
    setRefreshing(true)
    setFlashMessage(null)
    setIsError(false)
    try {
      const res = await apiFetch<{ flash: string }>('/orders/refresh', {
        method: 'POST',
        body: JSON.stringify({
          job_type: jobType,
          date_from: dateFrom || undefined,
          date_to: dateTo || undefined,
        }),
      })
      setFlashMessage(res.flash)
      setIsError(res.flash.includes('thất bại') || res.flash.includes('lỗi'))
      setShowCrawlModal(false)

      // Dispatch live update event so active views refresh immediately without destroying the toast popup
      window.dispatchEvent(new CustomEvent('orders-updated'))
    } catch (e: any) {
      setIsError(true)
      setFlashMessage(e?.message || 'Quét đơn thất bại — kiểm tra cấu hình tài khoản Printerval API.')
    } finally {
      setRefreshing(false)
    }
  }

  if (!user) return null

  return (
    <header className="h-16 bg-white border-b border-[hsl(var(--border))] sticky top-0 z-40 px-6 flex justify-between items-center shadow-xs">
      {/* Title & Breadcrumb */}
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-bold tracking-tight text-[hsl(var(--foreground))]">
          {getPageTitle(location.pathname)}
        </h2>
        <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 font-mono border border-blue-200">
          V1.0
        </span>
      </div>

      {/* Toast Notification Banner */}
      {flashMessage && (
        <div className={`fixed top-4 right-6 z-50 p-3 px-4 rounded-xl text-xs font-semibold shadow-lg flex items-center gap-2.5 transition-all animate-in fade-in slide-in-from-top-2 ${
          isError ? 'bg-red-600 text-white' : 'bg-[#0052CC] text-white'
        }`}>
          {isError ? <AlertCircle className="h-4 w-4 text-red-200 shrink-0" /> : <CheckCircle2 className="h-4 w-4 text-emerald-300 shrink-0" />}
          <span>{flashMessage}</span>
          <button onClick={() => setFlashMessage(null)} className="ml-2 p-0.5 hover:bg-white/20 rounded-md transition-colors">
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* Action Controls */}
      <div className="flex items-center gap-3">
        {user.role === 'admin' && (
          <>
            <button
              onClick={() => setShowSettingsModal(true)}
              className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold bg-blue-50/80 hover:bg-blue-100/80 border border-blue-200 text-[#0052CC] rounded-xl shadow-2xs transition-all cursor-pointer"
              title="Click để đổi Workspace hoặc Đăng nhập Acc Mẹ Printerval mới"
            >
              <KeyRound className="h-4 w-4 text-[#0052CC]" />
              <span>Acc Mẹ Printerval:</span>
              <strong className="font-mono text-slate-800 bg-white px-2 py-0.5 rounded border border-blue-100">
                {activePlatform?.account_username || 'Chưa chọn Acc Mẹ'}
              </strong>
            </button>

            <button
              onClick={() => setShowCrawlModal(true)}
              disabled={refreshing}
              className={`flex items-center gap-2 px-3.5 py-1.5 text-xs font-semibold rounded-xl border transition-all ${
                refreshing
                  ? 'bg-blue-50 text-[#0052CC] border-blue-300 shadow-inner'
                  : 'bg-[#0052CC] hover:bg-[#0041A3] border-transparent text-white shadow-2xs'
              } disabled:opacity-75 cursor-pointer`}
              title="Quét đơn mới từ Printerval API"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin text-white' : 'text-white'}`} />
              <span>{refreshing ? 'Đang Quét Đơn...' : 'Quét Đơn Printerval'}</span>
            </button>
          </>
        )}

        {/* Bell Notifications */}
        <div className="relative">
          <button className="p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors">
            <Bell className="h-5 w-5" />
            <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-amber-500 ring-2 ring-white"></span>
          </button>
        </div>

        <div className="h-6 w-px bg-slate-200"></div>

        {/* Logout */}
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 px-3 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-50 rounded-lg transition-colors border border-red-100 cursor-pointer"
        >
          <LogOut className="h-3.5 w-3.5" />
          <span>Đăng xuất</span>
        </button>
      </div>

      <PrintervalSettingsModal
        isOpen={showSettingsModal}
        onClose={() => setShowSettingsModal(false)}
      />
      <CrawlFilterModal
        isOpen={showCrawlModal}
        onClose={() => setShowCrawlModal(false)}
        onSearch={handleRefreshCrawl}
        loading={refreshing}
      />
    </header>
  )
}
