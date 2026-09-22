import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { usePlatform } from '../auth/PlatformContext'
import { apiFetch } from '../api/client'
import { Bell, LogOut, RefreshCw, AlertCircle, KeyRound, Images, Loader2, Pause, Play, Menu, MoreHorizontal, Send } from 'lucide-react'
import { PlatformSettingsModal } from './PlatformSettingsModal'
import { CrawlFilterModal } from './CrawlFilterModal'
import { SyncGalleryModal } from './SyncGalleryModal'
import { TelegramModal } from './TelegramModal'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { useGallerySync } from '../context/GallerySyncContext'
import { useToast } from '../context/ToastContext'

interface TopbarProps {
  onOpenNavigation: () => void
}

export function Topbar({ onOpenNavigation }: TopbarProps) {
  const { user, logout } = useAuth()
  const { activePlatform } = usePlatform()
  const navigate = useNavigate()
  const location = useLocation()
  const [refreshing, setRefreshing] = useState(false)
  const [showSettingsModal, setShowSettingsModal] = useState(false)
  const [showCrawlModal, setShowCrawlModal] = useState(false)
  const [showTelegramModal, setShowTelegramModal] = useState(false)
  const [crawlDesigners, setCrawlDesigners] = useState<string[]>([])
  const [isFastSyncing, setIsFastSyncing] = useState(false)
  const [fastSyncError, setFastSyncError] = useState<string | null>(null)
  const [mobileActionsOpen, setMobileActionsOpen] = useState(false)
  const { status: syncStatus, triggerRun } = useSyncStatus()
  const isStatusSyncing = isFastSyncing || syncStatus?.is_running === true
  const syncProgress = syncStatus?.progress
  const syncProcessed = typeof syncProgress?.processed === 'number' ? syncProgress.processed : null
  const syncTotal = typeof syncProgress?.total === 'number' ? syncProgress.total : null
  const syncPhase = typeof syncProgress?.phase === 'string' ? syncProgress.phase : null
  const syncCurrentOrder = typeof syncProgress?.current_order_code === 'string'
    ? syncProgress.current_order_code
    : null
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
    if (path === '/platform-hub' || path === '/platform-login') return 'Mở Hệ Thống Mẹ & Đồng Bộ Ảnh'
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
    const onStart = () => setIsFastSyncing(true)
    const onEnd = () => setIsFastSyncing(false)
    const onSubmitted = () => {
      setFastSyncError(null)
      setIsFastSyncing(true)
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

  async function handleSyncAllOrders() {
    setIsFastSyncing(true)
    setFastSyncError(null)
    window.dispatchEvent(new CustomEvent('sync-platform-start'))

    try {
      await triggerRun(null)
      showToast('Đã bắt đầu đồng bộ trạng thái hàng đợi đang xử lý từ Hệ thống mẹ.', 'success')
    } catch (e: any) {
      const message = e?.message || 'Đồng bộ thất bại.'
      setFastSyncError(message)
      showToast(message, 'error')
    } finally {
      setIsFastSyncing(false)
      window.dispatchEvent(new CustomEvent('sync-platform-end'))
    }
  }



  async function handleRefreshCrawl(jobType: string, status: string, designer: string, dateFrom: string, dateTo: string, deadlineTacahu: string) {
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
          deadline_tacahu: deadlineTacahu,
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

  function openCrawlFilter() {
    apiFetch<{ orders: { platform_designer?: string | null }[] }>('/orders')
      .then((result) => {
        const options = result.orders
          .map((order) => order.platform_designer)
          .filter((item): item is string => Boolean(item))
        setCrawlDesigners(Array.from(new Set(options)).sort())
      })
      .catch(() => setCrawlDesigners([]))
    setShowCrawlModal(true)
  }

  if (!user) return null

  return (
    <header className="relative sticky top-0 z-40 flex h-16 items-center justify-between border-b border-[hsl(var(--border))] bg-white px-3 shadow-xs sm:px-5 xl:px-6">
      {/* Title & Breadcrumb */}
      <div className="flex min-w-0 items-center gap-2 sm:gap-3">
        <button
          type="button"
          onClick={onOpenNavigation}
          className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 md:hidden"
          aria-label="Mở điều hướng"
        >
          <Menu className="h-5 w-5" />
        </button>
        <h2 className="truncate text-base font-bold tracking-tight text-[hsl(var(--foreground))] sm:text-lg">
          {getPageTitle(location.pathname)}
        </h2>
        <span className="hidden rounded-full border border-blue-200 bg-blue-50 px-2 py-0.5 font-mono text-xs text-blue-700 sm:inline">
          V1.3
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
      <div className="flex shrink-0 items-center gap-1 sm:gap-2 xl:gap-3">
        {(user.role === 'admin' || user.role === 'support') && (
          <button
            onClick={() => user.role === 'admin' ? setShowSettingsModal(true) : null}
            className={`hidden items-center gap-2 rounded-xl border border-blue-200 bg-blue-50/80 px-3 py-1.5 text-xs font-semibold text-[#0052CC] shadow-2xs transition-all xl:flex ${user.role === 'admin' ? 'cursor-pointer hover:bg-blue-100/80' : 'cursor-default'}`}
            title={user.role === 'admin' ? "Click để đổi Workspace hoặc Đăng nhập Acc Mẹ mới" : "Acc Mẹ đang hoạt động"}
          >
            <KeyRound className="h-4 w-4 text-[#0052CC]" />
            <span>Acc Mẹ:</span>
            <strong className="font-mono text-slate-800 bg-white px-2 py-0.5 rounded border border-blue-100">
              {activePlatform?.account_username || 'Chưa chọn Acc Mẹ'}
            </strong>
          </button>
        )}

        {user.role === 'admin' && (
          <button
            type="button"
            onClick={() => setShowSettingsModal(true)}
            className="hidden rounded-lg p-2 text-[#0052CC] hover:bg-blue-50 md:inline-flex xl:hidden"
            title="Cấu hình tài khoản Print"
          >
            <KeyRound className="h-4 w-4" />
          </button>
        )}

        {user.role === 'admin' && (
          <>

            <button
              onClick={openCrawlFilter}
              disabled={refreshing}
              className={`hidden items-center gap-2 rounded-xl border px-3.5 py-1.5 text-xs font-semibold transition-all md:flex ${
                refreshing
                  ? 'bg-blue-50 text-[#0052CC] border-blue-300 shadow-inner'
                  : 'bg-[#0052CC] hover:bg-[#0041A3] border-transparent text-white shadow-2xs'
              } disabled:opacity-75 cursor-pointer`}
              title="Quét đơn mới từ Print API"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin text-white' : 'text-white'}`} />
              <span className="hidden xl:inline">{refreshing ? 'Đang Quét Đơn...' : 'Quét Đơn Print'}</span>
            </button>

            {/* Gallery Sync Button / Live Progress Bar */}
            {!isGallerySyncing ? (
              <button
                type="button"
                onClick={() => triggerSyncWaiting(false)}
              className="hidden items-center gap-1.5 rounded-xl border border-purple-200 bg-purple-50 px-3.5 py-1.5 text-xs font-semibold text-purple-700 shadow-2xs transition-all hover:bg-purple-100 md:flex"
                title="Đồng bộ bộ ảnh cho toàn bộ đơn trong Waiting (tự động bỏ qua các đơn đã có đủ ảnh)"
              >
                <Images className="h-3.5 w-3.5 text-purple-600" />
                <span className="hidden xl:inline">Đồng bộ bộ ảnh</span>
                {pendingWaitingCount > 0 && (
                  <span className="px-1.5 py-0.2 rounded-full bg-purple-200/80 text-purple-900 text-[10px] font-bold font-mono">
                    {pendingWaitingCount}
                  </span>
                )}
              </button>
            ) : (
              <div className="hidden items-center gap-1.5 md:flex">
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
          type="button"
          onClick={handleSyncAllOrders}
          disabled={isStatusSyncing}
          title={
            isStatusSyncing
              ? `Đang ${syncPhase || 'đồng bộ'}${syncProcessed !== null && syncTotal !== null ? ` ${syncProcessed}/${syncTotal}` : ''}${syncCurrentOrder ? ` · ${syncCurrentOrder}` : ''}`
              : fastSyncError || syncStatus?.last_error
              ? `Lần đồng bộ trước lỗi: ${fastSyncError || syncStatus?.last_error}`
              : 'Bấm để đồng bộ lại trạng thái toàn bộ đơn hàng trong database từ Hệ thống mẹ'
          }
          className={`inline-flex items-center gap-1.5 rounded-xl border px-3 py-1.5 text-xs font-semibold transition-all cursor-pointer disabled:cursor-wait ${
            isStatusSyncing
              ? 'bg-blue-50/90 border-blue-200 text-[#0052CC] shadow-xs'
              : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50 hover:border-slate-300 shadow-2xs'
          }`}
        >
          <RefreshCw
            className={`h-4 w-4 shrink-0 ${
              isStatusSyncing ? 'animate-spin text-[#0052CC]' : 'text-slate-500'
            }`}
          />
          <span>
            {isStatusSyncing
              ? syncProcessed !== null && syncTotal !== null && syncTotal > 0
                ? `Đang đồng bộ ${syncProcessed}/${syncTotal}`
                : 'Đang đồng bộ'
              : 'Đồng bộ'}
          </span>
          <span
            className={`h-2 w-2 rounded-full shrink-0 ${
              isStatusSyncing
                ? 'bg-[#0052CC] animate-pulse'
                : fastSyncError || syncStatus?.last_error
                ? 'bg-red-500'
                : 'bg-emerald-500'
            }`}
          />
        </button>

        {/* Telegram Bot Connection */}
        <button
          type="button"
          onClick={() => setShowTelegramModal(true)}
          className="flex items-center gap-1.5 rounded-lg border border-sky-100 bg-sky-50 px-2.5 py-1.5 text-xs font-semibold text-sky-700 hover:bg-sky-100 transition-colors"
          title="Kết nối Telegram Bot để nhận thông báo"
        >
          <Send className="h-3.5 w-3.5 -translate-x-0.5 translate-y-0.5 text-sky-500" />
          <span className="hidden md:inline">Telegram</span>
        </button>

        {/* Bell Notifications */}
        <div className="relative">
          <button className="p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors">
            <Bell className="h-5 w-5" />
            <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-amber-500 ring-2 ring-white"></span>
          </button>
        </div>

        <div className="hidden h-6 w-px bg-slate-200 sm:block"></div>

        {/* Logout */}
        <button
          onClick={handleLogout}
          className="hidden items-center gap-2 rounded-lg border border-red-100 px-3 py-1.5 text-xs font-semibold text-red-600 transition-colors hover:bg-red-50 sm:flex"
        >
          <LogOut className="h-3.5 w-3.5" />
          <span>Đăng xuất</span>
        </button>

        <button
          type="button"
          onClick={() => setMobileActionsOpen((current) => !current)}
          className="rounded-lg p-2 text-slate-600 hover:bg-slate-100 sm:hidden"
          aria-label="Mở thao tác nhanh"
          aria-expanded={mobileActionsOpen}
        >
          <MoreHorizontal className="h-5 w-5" />
        </button>
      </div>

      {mobileActionsOpen && (
        <div className="absolute right-3 top-[calc(100%+0.5rem)] z-50 w-60 rounded-xl border border-slate-200 bg-white p-1.5 shadow-xl sm:hidden">
          <button type="button" onClick={() => { setShowTelegramModal(true); setMobileActionsOpen(false) }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-xs font-semibold text-sky-700 hover:bg-sky-50">
            <Send className="h-4 w-4 text-sky-500" /> Kết nối Telegram
          </button>
          {user.role === 'admin' && (
            <>
              <button type="button" onClick={() => { setShowSettingsModal(true); setMobileActionsOpen(false) }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-xs font-semibold text-slate-700 hover:bg-slate-50">
                <KeyRound className="h-4 w-4 text-[#0052CC]" /> Tài khoản Print
              </button>
              <button type="button" onClick={() => { openCrawlFilter(); setMobileActionsOpen(false) }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-xs font-semibold text-slate-700 hover:bg-slate-50">
                <RefreshCw className="h-4 w-4 text-[#0052CC]" /> Quét đơn Print
              </button>
              <button type="button" onClick={() => { triggerSyncWaiting(false); setMobileActionsOpen(false) }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-xs font-semibold text-slate-700 hover:bg-slate-50">
                <Images className="h-4 w-4 text-purple-600" /> Đồng bộ bộ ảnh
              </button>
            </>
          )}
          <button type="button" onClick={() => { void handleLogout(); setMobileActionsOpen(false) }} className="flex w-full items-center gap-2 rounded-lg px-3 py-2.5 text-left text-xs font-semibold text-red-600 hover:bg-red-50">
            <LogOut className="h-4 w-4" /> Đăng xuất
          </button>
        </div>
      )}

      {/* Workspace / Platform Account Settings Modal */}
      <PlatformSettingsModal
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
      <TelegramModal
        isOpen={showTelegramModal}
        onClose={() => setShowTelegramModal(false)}
      />
      <SyncGalleryModal />
    </header>
  )
}
