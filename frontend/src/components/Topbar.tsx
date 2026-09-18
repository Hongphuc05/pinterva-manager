import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { usePlatform } from '../auth/PlatformContext'
import { apiFetch } from '../api/client'
import { Bell, LogOut, RefreshCw, AlertCircle, KeyRound, Images, Loader2, Pause, Play } from 'lucide-react'
import { PrintervalSettingsModal } from './PrintervalSettingsModal'
import { CrawlFilterModal } from './CrawlFilterModal'
import { SyncGalleryModal } from './SyncGalleryModal'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { useGallerySync } from '../context/GallerySyncContext'
import { useToast } from '../context/ToastContext'

export function Topbar() {
  const { user, logout } = useAuth()
  const { activePlatform } = usePlatform()
  const navigate = useNavigate()
  const location = useLocation()
  const [refreshing, setRefreshing] = useState(false)
  const [showSettingsModal, setShowSettingsModal] = useState(false)
  const [showCrawlModal, setShowCrawlModal] = useState(false)
  const [crawlDesigners, setCrawlDesigners] = useState<string[]>([])
  const [isFastSyncing, setIsFastSyncing] = useState(false)
  const [fastSyncError, setFastSyncError] = useState<string | null>(null)
  const { status: syncStatus, triggerRun } = useSyncStatus()
  const {
    isSyncing: isGallerySyncing,
    isPaused: isGalleryPaused,
    pauseSync,
    resumeSync,
    progress: galleryProgress,
    pendingWaitingCount,
    openModal: openGalleryModal,
    triggerSyncWaiting,
  } = useGallerySync()

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
    if (path === '/kanban') return 'Board Đơn trùng lặp'
    if (path === '/my-tasks') return 'My Tasks'
    if (path === '/printerval-hub' || path === '/printerval-login') return 'Mở Print & Đồng Bộ Ảnh'
    if (path === '/order-status') return 'Trạng Thái Đơn'
    if (path === '/users') return 'Quản Lý Tài Khoản'
    return 'Dashboard'
  }

  const { showToast } = useToast()

  // Listen for gallery sync notification events
  useEffect(() => {
    function onGalleryNotify(e: any) {
      if (e.detail?.message) {
        showToast(e.detail.message, e.detail.type || 'info')
      }
    }
    window.addEventListener('gallery-sync-notify', onGalleryNotify)
    return () => window.removeEventListener('gallery-sync-notify', onGalleryNotify)
  }, [showToast])

  // Listen for sync-platform events to drive the circular animation
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
    window.addEventListener('sync-platform-start', onStart)
    window.addEventListener('sync-platform-end', onEnd)
    window.addEventListener('sync-platform-submitted', onSubmitted)
    return () => {
      window.removeEventListener('sync-platform-start', onStart)
      window.removeEventListener('sync-platform-end', onEnd)
      window.removeEventListener('sync-platform-submitted', onSubmitted)
    }
  }, [])

  async function handleRefreshCurrentTab() {
    setIsFastSyncing(true)
    setFastSyncError(null)
    window.dispatchEvent(new CustomEvent('sync-platform-start'))

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
        window.dispatchEvent(new CustomEvent('sync-platform-submitted'))
      } catch (err: any) {
        setFastSyncError(err?.message || 'Lỗi khi đồng bộ từ Web mẹ')
      } finally {
        setIsFastSyncing(false)
        window.dispatchEvent(new CustomEvent('sync-platform-end'))
      }
    }
  }

  async function handleRefreshCrawl(jobType: string, status: string, designer: string, dateFrom: string, dateTo: string) {
    setRefreshing(true)
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
      const isErr = res.flash.includes('thất bại') || res.flash.includes('lỗi')
      showToast(res.flash, isErr ? 'error' : 'success')
      setShowCrawlModal(false)

      // Dispatch live update event so active views refresh immediately without destroying the toast popup
      window.dispatchEvent(new CustomEvent('orders-updated'))
    } catch (e: any) {
      showToast(e?.message || 'Quét đơn thất bại — kiểm tra cấu hình tài khoản Print API.', 'error')
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
          V1.2
        </span>
      </div>

      {/* Persistent Warning Banner for Expired Session Cookie / Sync Error */}
      {syncStatus?.last_error && user.role === 'admin' && (() => {
        const err = syncStatus.last_error.toLowerCase()
        const isAuthCookieError =
          err.includes('cookie') ||
          err.includes('hết hạn') ||
          err.includes('xác thực') ||
          err.includes('unauthorized') ||
          err.includes('401') ||
          err.includes('session') ||
          err.includes('đăng nhập') ||
          err.includes('login')

        const displayMessage = err.includes('update statement on table')
          ? 'Xung đột dữ liệu tạm thời khi đồng bộ (hệ thống sẽ tự thử lại)'
          : syncStatus.last_error

        return (
          <div className="hidden md:flex items-center gap-2 bg-amber-50 border border-amber-300 text-amber-900 px-3 py-1 rounded-xl text-xs font-medium">
            <AlertCircle className="h-4 w-4 text-amber-600 shrink-0" />
            <span className="truncate max-w-sm" title={syncStatus.last_error}>
              {displayMessage}
            </span>
            {isAuthCookieError && (
              <button
                onClick={() => setShowSettingsModal(true)}
                className="ml-1 px-2 py-0.5 bg-amber-600 text-white rounded font-bold text-[10px] hover:bg-amber-700 transition-colors cursor-pointer shrink-0"
              >
                Cập nhật Cookie
              </button>
            )}
          </div>
        )
      })()}

      {/* Action Controls */}
      <div className="flex items-center gap-3">
        {(user.role === 'admin' || user.role === 'support') && (
          <button
            onClick={() => user.role === 'admin' ? setShowSettingsModal(true) : null}
            className={`flex items-center gap-2 px-3 py-1.5 text-xs font-semibold bg-blue-50/80 hover:bg-blue-100/80 border border-blue-200 text-[#0052CC] rounded-xl shadow-2xs transition-all ${user.role === 'admin' ? 'cursor-pointer' : 'cursor-default'}`}
            title={user.role === 'admin' ? "Click để đổi Workspace hoặc Đăng nhập Acc Mẹ Print mới" : "Acc Mẹ Print đang hoạt động"}
          >
            <KeyRound className="h-4 w-4 text-[#0052CC]" />
            <span>Acc Mẹ Print:</span>
            <strong className="font-mono text-slate-800 bg-white px-2 py-0.5 rounded border border-blue-100">
              {activePlatform?.account_username || 'Chưa chọn Acc Mẹ'}
            </strong>
          </button>
        )}

        {user.role === 'admin' && (
          <>

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
              title="Quét đơn mới từ Print API"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin text-white' : 'text-white'}`} />
              <span>{refreshing ? 'Đang Quét Đơn...' : 'Quét Đơn Print'}</span>
            </button>

            {/* Gallery Sync Button / Live Progress Bar */}
            {!isGallerySyncing ? (
              <button
                type="button"
                onClick={() => triggerSyncWaiting(false)}
                className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-xl bg-purple-50 hover:bg-purple-100 text-purple-700 border border-purple-200 shadow-2xs transition-all cursor-pointer"
                title="Đồng bộ bộ ảnh cho toàn bộ đơn trong Waiting (tự động bỏ qua các đơn đã có đủ ảnh)"
              >
                <Images className="h-3.5 w-3.5 text-purple-600" />
                <span>Đồng bộ bộ ảnh</span>
                {pendingWaitingCount > 0 && (
                  <span className="px-1.5 py-0.2 rounded-full bg-purple-200/80 text-purple-900 text-[10px] font-bold font-mono">
                    {pendingWaitingCount}
                  </span>
                )}
              </button>
            ) : (
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={openGalleryModal}
                  className={`relative flex items-center gap-2 px-3.5 py-1.5 text-xs font-bold rounded-xl text-white shadow-md transition-all cursor-pointer overflow-hidden border select-none ${
                    isGalleryPaused
                      ? 'bg-amber-600 hover:bg-amber-700 border-amber-400/40'
                      : 'bg-purple-600 hover:bg-purple-700 border-purple-400/40'
                  }`}
                  title="Bấm để xem chi tiết tiến trình từng đơn"
                >
                  {galleryProgress && (
                    <div
                      className={`absolute inset-0 transition-all duration-300 pointer-events-none ${
                        isGalleryPaused ? 'bg-amber-900/40' : 'bg-purple-900/40'
                      }`}
                      style={{ width: `${Math.round((galleryProgress.current / galleryProgress.total) * 100)}%` }}
                    />
                  )}
                  {!isGalleryPaused ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-white relative z-10 shrink-0" />
                  ) : (
                    <Pause className="h-3.5 w-3.5 text-amber-200 relative z-10 shrink-0" />
                  )}
                  <span className="relative z-10 font-mono">
                    {isGalleryPaused ? 'Tạm dừng đồng bộ' : 'Đang đồng bộ ảnh'}{' '}
                    {galleryProgress ? `${galleryProgress.current}/${galleryProgress.total}` : '...'}
                  </span>
                  {galleryProgress && (
                    <span className="relative z-10 text-[10px] bg-white/20 px-1.5 py-0.5 rounded font-mono font-bold">
                      {Math.round((galleryProgress.current / galleryProgress.total) * 100)}%
                    </span>
                  )}
                </button>

                {/* Pause / Resume Quick Button */}
                <button
                  type="button"
                  onClick={isGalleryPaused ? resumeSync : pauseSync}
                  className={`p-1.5 rounded-xl border transition-all cursor-pointer shadow-2xs ${
                    isGalleryPaused
                      ? 'bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border-emerald-300'
                      : 'bg-amber-50 hover:bg-amber-100 text-amber-700 border-amber-300'
                  }`}
                  title={isGalleryPaused ? 'Tiếp tục đồng bộ ảnh' : 'Tạm dừng đồng bộ ảnh'}
                >
                  {isGalleryPaused ? (
                    <Play className="h-4 w-4 fill-emerald-600 text-emerald-600" />
                  ) : (
                    <Pause className="h-4 w-4 fill-amber-600 text-amber-600" />
                  )}
                </button>
              </div>
            )}
          </>
        )}

        {/* Status-sync indicator: green = idle/ok, red = last run errored, spins
            while actively syncing. Refreshes the orders present in the currently active tab. */}
        <button
          onClick={handleRefreshCurrentTab}
          disabled={isFastSyncing || !!syncStatus?.is_running}
          title={
            isFastSyncing || syncStatus?.is_running
              ? 'Đang đồng bộ trạng thái đơn từ Print...'
              : fastSyncError || syncStatus?.last_error
              ? `Lần đồng bộ trước lỗi: ${fastSyncError || syncStatus?.last_error}`
              : 'Bấm để làm mới trạng thái các đơn trong tab đang chọn từ Print'
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
      <SyncGalleryModal />
    </header>
  )
}
