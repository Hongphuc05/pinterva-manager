import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { usePlatform } from '../auth/PlatformContext'
import { apiFetch } from '../api/client'
import { Bell, LogOut, RefreshCw, CheckCircle2, AlertCircle, X, KeyRound } from 'lucide-react'
import { PrintervalSettingsModal } from './PrintervalSettingsModal'
import { CrawlFilterModal } from './CrawlFilterModal'
import { useSyncStatus } from '../hooks/useSyncStatus'

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
  const [crawlDesigners, setCrawlDesigners] = useState<string[]>([])
  const [isFastSyncing, setIsFastSyncing] = useState(false)
  const [fastSyncError, setFastSyncError] = useState<string | null>(null)
  const { status: syncStatus, triggerRun } = useSyncStatus()

  async function handleLogout() {
    await logout()
    navigate('/login')
  }

  function getPageTitle(path: string) {
    if (path.startsWith('/orders/')) return 'Chi Tiết Đơn Hàng'
    if (path === '/orders') return user?.role === 'designer' ? 'My Tasks' : 'Danh Sách Đơn Hàng'
    if (path === '/designer-board') return 'Tiến Độ Designer'
    if (path === '/order-history') return user?.role === 'designer' ? 'Lịch Sử Của Tôi' : 'Lịch Sử Hoạt Động & Tiến Độ'
    if (path === '/allocation') return 'Phân Bổ Kéo-Thả'
    if (path === '/kanban') return 'Bảng Tiến Độ Kanban'
    if (path === '/my-tasks') return 'My Tasks'
    if (path === '/printerval-login') return 'Đăng Nhập Printerval'
    if (path === '/order-status') return 'Trạng Thái Đơn'
    if (path === '/users') return 'Quản Lý Tài Khoản'
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

  // Listen for sync-printerval events to drive the circular animation
  useEffect(() => {
    function onStart() {
      setIsFastSyncing(true)
      setFastSyncError(null)
    }
    function onEnd() {
      setIsFastSyncing(false)
    }
    function onSubmitted() {
      setIsFastSyncing(false)
    }
    window.addEventListener('sync-printerval-start', onStart)
    window.addEventListener('sync-printerval-end', onEnd)
    window.addEventListener('sync-printerval-submitted', onSubmitted)
    return () => {
      window.removeEventListener('sync-printerval-start', onStart)
      window.removeEventListener('sync-printerval-end', onEnd)
      window.removeEventListener('sync-printerval-submitted', onSubmitted)
    }
  }, [])

  async function handleRefreshCurrentTab() {
    setIsFastSyncing(true)
    setFastSyncError(null)
    window.dispatchEvent(new CustomEvent('sync-printerval-start'))

    let handled = false
    const onHandled = () => {
      handled = true
    }
    window.addEventListener('sync-tab-handled', onHandled, { once: true })
    window.dispatchEvent(new CustomEvent('request-sync-current-tab'))

    // Wait a brief moment to check if an active view handled syncing its specific tab
    await new Promise((r) => setTimeout(r, 60))
    window.removeEventListener('sync-tab-handled', onHandled)

    if (!handled) {
      try {
        await triggerRun()
        window.dispatchEvent(new CustomEvent('sync-printerval-submitted'))
      } catch (err: any) {
        setFastSyncError(err?.message || 'Lỗi khi đồng bộ từ Printerval')
      } finally {
        setIsFastSyncing(false)
        window.dispatchEvent(new CustomEvent('sync-printerval-end'))
      }
    }
  }

  async function handleRefreshCrawl(jobType: string, status: string, designer: string, dateFrom: string, dateTo: string) {
    setRefreshing(true)
    setFlashMessage(null)
    setIsError(false)
    try {
      const res = await apiFetch<{ flash: string }>('/orders/refresh', {
        method: 'POST',
        body: JSON.stringify({
          job_type: jobType,
          printerval_status: status,
          printerval_designer: designer || undefined,
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

      {/* Persistent Warning Banner for Expired Session Cookie / Sync Error */}
      {syncStatus?.last_error && user.role === 'admin' && (
        <div className="hidden md:flex items-center gap-2 bg-amber-50 border border-amber-300 text-amber-900 px-3 py-1 rounded-xl text-xs font-medium">
          <AlertCircle className="h-4 w-4 text-amber-600 shrink-0" />
          <span className="truncate max-w-sm" title={syncStatus.last_error}>
            {syncStatus.last_error}
          </span>
          <button
            onClick={() => setShowSettingsModal(true)}
            className="ml-1 px-2 py-0.5 bg-amber-600 text-white rounded font-bold text-[10px] hover:bg-amber-700 transition-colors cursor-pointer shrink-0"
          >
            Cập nhật Cookie
          </button>
        </div>
      )}

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
              onClick={() => {
                apiFetch<{ orders: { printerval_designer: string | null }[] }>('/orders')
                  .then((result) => {
                    const options = result.orders
                      .map((order) => order.printerval_designer)
                      .filter((item): item is string => Boolean(item))
                    setCrawlDesigners(Array.from(new Set(options)).sort())
                  })
                  .catch(() => setCrawlDesigners([]))
                setShowCrawlModal(true)
              }}
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

        {/* Status-sync indicator: green = idle/ok, red = last run errored, spins
            while actively syncing. Refreshes the orders present in the currently active tab. */}
        <button
          onClick={handleRefreshCurrentTab}
          disabled={isFastSyncing || !!syncStatus?.is_running}
          title={
            isFastSyncing || syncStatus?.is_running
              ? 'Đang đồng bộ trạng thái đơn từ Printerval...'
              : fastSyncError || syncStatus?.last_error
              ? `Lần đồng bộ trước lỗi: ${fastSyncError || syncStatus?.last_error}`
              : 'Bấm để làm mới trạng thái các đơn trong tab đang chọn từ Printerval'
          }
          className="relative p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer disabled:cursor-wait"
        >
          <RefreshCw
            className={`h-5 w-5 ${
              isFastSyncing || syncStatus?.is_running ? 'animate-spin text-[#0052CC]' : ''
            }`}
          />
          <span
            className={`absolute top-1.5 right-1.5 h-2 w-2 rounded-full ring-2 ring-white ${
              isFastSyncing || syncStatus?.is_running
                ? 'bg-[#0052CC] animate-pulse'
                : fastSyncError || syncStatus?.last_error
                ? 'bg-red-500'
                : 'bg-emerald-500'
            }`}
          />
        </button>

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
        designers={crawlDesigners}
      />
    </header>
  )
}
