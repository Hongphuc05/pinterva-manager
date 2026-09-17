import { useState, useMemo } from 'react'
import {
  X,
  Images,
  Loader2,
  AlertCircle,
  ExternalLink,
  Sparkles,
  Search,
  RefreshCw,
  Check,
  Pause,
  Play,
  ArrowUpCircle,
} from 'lucide-react'
import { useGallerySync } from '../context/GallerySyncContext'

export function SyncGalleryModal() {
  const {
    isModalOpen,
    closeModal,
    isSyncing,
    isPaused,
    pauseSync,
    resumeSync,
    progress,
    waitingOrders,
    syncStatusMap,
    isExtensionConnected,
    triggerSyncWaiting,
    prioritizeOrder,
    loadWaitingOrders,
  } = useGallerySync()

  const [searchQuery, setSearchQuery] = useState('')
  const [filterMode, setFilterMode] = useState<'all' | 'pending' | 'synced' | 'error'>('all')
  const [loadingList, setLoadingList] = useState(false)

  const getOrderEffectiveCount = (o: { id: string; image_count: number }) => {
    const live = syncStatusMap[o.id]
    if (live?.status === 'success' && typeof live.count === 'number') {
      return Math.max(live.count, o.image_count)
    }
    return o.image_count
  }

  const pendingCount = waitingOrders.filter(
    (o) => getOrderEffectiveCount(o) <= 1 && syncStatusMap[o.id]?.status !== 'error'
  ).length
  const syncedCount = waitingOrders.filter((o) => getOrderEffectiveCount(o) > 1).length
  const errorCount = waitingOrders.filter((o) => syncStatusMap[o.id]?.status === 'error').length

  const filteredOrders = useMemo(() => {
    return waitingOrders.filter((o) => {
      const matchSearch =
        !searchQuery ||
        o.external_order_id.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (o.product_name && o.product_name.toLowerCase().includes(searchQuery.toLowerCase()))

      const currentCount = getOrderEffectiveCount(o)
      const isError = syncStatusMap[o.id]?.status === 'error'

      if (filterMode === 'pending') {
        return matchSearch && currentCount <= 1 && !isError
      }
      if (filterMode === 'synced') {
        return matchSearch && currentCount > 1
      }
      if (filterMode === 'error') {
        return matchSearch && isError
      }
      return matchSearch
    })
  }, [waitingOrders, searchQuery, filterMode, syncStatusMap])

  if (!isModalOpen) return null

  const progressPercent = progress ? Math.round((progress.current / progress.total) * 100) : 0

  async function handleRetryAllErrors() {
    const errorOrders = waitingOrders.filter((o) => syncStatusMap[o.id]?.status === 'error')
    for (const ord of errorOrders) {
      await prioritizeOrder(ord)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 animate-in fade-in duration-200"
      onClick={closeModal}
    >
      <div
        className="relative w-full max-w-3xl bg-white rounded-2xl shadow-2xl overflow-hidden flex flex-col border border-slate-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 bg-slate-50">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-purple-100 text-purple-700">
              <Images className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-800">Tiến Độ Đồng Bộ Bộ Ảnh (Tab Waiting)</h2>
              <p className="text-xs text-slate-500">
                Tự động cào trọn bộ ảnh cho đơn Waiting và cập nhật tức thì cho Designer
              </p>
            </div>
          </div>
          <button
            onClick={closeModal}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200 transition-colors cursor-pointer"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-4 max-h-[75vh] overflow-y-auto">
          {!isExtensionConnected && (
            <div className="p-3.5 rounded-xl bg-amber-50 border border-amber-300 text-amber-900 text-xs flex items-start gap-2.5">
              <AlertCircle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-bold">Gợi ý kết nối Extension (Tự động hỗ trợ vượt Cloudflare):</p>
                <p className="text-amber-800 leading-relaxed text-[11px]">
                  Nếu trang sản phẩm yêu cầu xác thực, hãy mở{' '}
                  <code className="bg-amber-100 px-1 py-0.5 rounded font-mono font-bold">chrome://extensions</code> và
                  bấm <strong>Reload 🔄</strong> extension <strong>Printerval Admin POD Tool</strong>.
                </p>
              </div>
            </div>
          )}

          {/* Active Live Progress Bar Card with Pause / Resume */}
          {isSyncing && progress && (
            <div
              className={`p-4 rounded-2xl border space-y-2.5 shadow-xs transition-colors ${
                isPaused
                  ? 'bg-amber-50/80 border-amber-200'
                  : 'bg-purple-50/80 border-purple-200'
              }`}
            >
              <div className="flex items-center justify-between text-xs flex-wrap gap-2">
                <div
                  className={`flex items-center gap-2 font-bold ${
                    isPaused ? 'text-amber-950' : 'text-purple-900'
                  }`}
                >
                  {!isPaused ? (
                    <Loader2 className="h-4 w-4 animate-spin text-purple-600" />
                  ) : (
                    <Pause className="h-4 w-4 text-amber-600" />
                  )}
                  <span>
                    {isPaused ? 'Đã tạm dừng đồng bộ:' : 'Đang đồng bộ ảnh:'} {progress.current}/{progress.total} đơn (
                    {progressPercent}%)
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  {progress.currentOrderCode && !isPaused && (
                    <span className="font-mono text-[11px] font-bold px-2 py-0.5 rounded bg-purple-200/80 text-purple-900">
                      Đang xử lý: {progress.currentOrderCode}
                    </span>
                  )}

                  {/* Pause / Resume button inside modal */}
                  <button
                    type="button"
                    onClick={isPaused ? resumeSync : pauseSync}
                    className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-bold transition-all shadow-2xs cursor-pointer ${
                      isPaused
                        ? 'bg-purple-600 hover:bg-purple-700 text-white'
                        : 'bg-white hover:bg-amber-100 text-amber-900 border border-amber-300'
                    }`}
                  >
                    {isPaused ? (
                      <>
                        <Play className="h-3.5 w-3.5 fill-white text-white" />
                        <span>Tiếp tục</span>
                      </>
                    ) : (
                      <>
                        <Pause className="h-3.5 w-3.5 fill-amber-700 text-amber-700" />
                        <span>Tạm dừng</span>
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Progress Bar Track */}
              <div
                className={`h-2.5 w-full rounded-full overflow-hidden ${
                  isPaused ? 'bg-amber-200' : 'bg-purple-200'
                }`}
              >
                <div
                  className={`h-full rounded-full transition-all duration-300 ${
                    isPaused ? 'bg-amber-600' : 'bg-purple-600'
                  }`}
                  style={{ width: `${progressPercent}%` }}
                />
              </div>

              <div
                className={`flex items-center justify-between text-[11px] ${
                  isPaused ? 'text-amber-800' : 'text-purple-700'
                }`}
              >
                <span>
                  Thành công: <strong>{progress.successCount}</strong> đơn
                </span>
                <span>
                  Còn lại: <strong>{progress.total - progress.current}</strong> đơn
                </span>
              </div>
            </div>
          )}

          {/* Quick Stats & Trigger Actions */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 p-4 bg-slate-50 rounded-xl border border-slate-200">
            <div className="flex items-center gap-4 text-xs font-medium text-slate-600">
              <div>
                Đơn Waiting: <strong className="text-slate-800 font-bold">{waitingOrders.length}</strong>
              </div>
              <div>
                Đã đủ ảnh: <strong className="text-emerald-600 font-bold">{syncedCount}</strong>
              </div>
              <div>
                Chỉ 1 ảnh: <strong className="text-amber-600 font-bold">{pendingCount}</strong>
              </div>
            </div>

            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                onClick={async () => {
                  setLoadingList(true)
                  await loadWaitingOrders()
                  setLoadingList(false)
                }}
                disabled={isSyncing && !isPaused}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-600 bg-white hover:bg-slate-100 rounded-lg border border-slate-200 shadow-2xs transition-all disabled:opacity-50 cursor-pointer"
                title="Tải lại danh sách đơn Waiting mới nhất"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${loadingList ? 'animate-spin' : ''}`} />
                <span>Làm mới</span>
              </button>

              {errorCount > 0 && (
                <button
                  type="button"
                  onClick={handleRetryAllErrors}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-bold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-xl transition-all shadow-2xs cursor-pointer"
                  title="Ưu tiên thử lại toàn bộ các đơn đang báo lỗi"
                >
                  <RefreshCw className="h-3.5 w-3.5 text-rose-600" />
                  <span>Ưu tiên thử lại đơn lỗi ({errorCount})</span>
                </button>
              )}

              <button
                type="button"
                onClick={() => triggerSyncWaiting(false)}
                disabled={isSyncing || pendingCount === 0}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-bold text-amber-900 bg-amber-100 hover:bg-amber-200 rounded-xl transition-all shadow-2xs disabled:opacity-50 cursor-pointer"
                title="Chỉ đồng bộ các đơn mới chưa có đủ bộ ảnh"
              >
                <Sparkles className="h-3.5 w-3.5 text-amber-700" />
                <span>Đồng bộ đơn thiếu ảnh ({pendingCount})</span>
              </button>

              <button
                type="button"
                onClick={() => triggerSyncWaiting(true)}
                disabled={isSyncing || waitingOrders.length === 0}
                className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-bold text-white bg-purple-600 hover:bg-purple-700 rounded-xl transition-all shadow-2xs disabled:opacity-60 cursor-pointer"
                title="Quét lại toàn bộ ảnh cho tất cả các đơn trong Waiting"
              >
                {isSyncing && !isPaused ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    <span>Đang xử lý...</span>
                  </>
                ) : (
                  <>
                    <Images className="h-3.5 w-3.5" />
                    <span>Quét lại tất cả ({waitingOrders.length})</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Search & Filter bar */}
          <div className="flex flex-col sm:flex-row items-center gap-2">
            <div className="relative flex-1 w-full">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
              <input
                type="text"
                placeholder="Tìm theo mã đơn (DJ...) hoặc tên sản phẩm..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-4 py-2 text-xs border border-slate-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#0052CC]/20 focus:border-[#0052CC]"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-3 top-2.5 text-xs text-slate-400 hover:text-slate-600"
                >
                  ✕
                </button>
              )}
            </div>

            <div className="flex items-center bg-slate-100 p-1 rounded-xl text-xs font-semibold shrink-0 gap-0.5 overflow-x-auto">
              <button
                onClick={() => setFilterMode('all')}
                className={`px-3 py-1 rounded-lg transition-colors cursor-pointer ${
                  filterMode === 'all' ? 'bg-white text-slate-800 shadow-xs' : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                Tất cả ({waitingOrders.length})
              </button>
              <button
                onClick={() => setFilterMode('pending')}
                className={`px-3 py-1 rounded-lg transition-colors cursor-pointer ${
                  filterMode === 'pending' ? 'bg-white text-amber-700 shadow-xs' : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                Thiếu ảnh ({pendingCount})
              </button>
              <button
                onClick={() => setFilterMode('error')}
                className={`px-3 py-1 rounded-lg transition-colors cursor-pointer ${
                  filterMode === 'error'
                    ? 'bg-white text-rose-700 shadow-xs font-bold'
                    : errorCount > 0
                    ? 'text-rose-600 font-semibold hover:text-rose-800'
                    : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                Lỗi / Thử lại ({errorCount})
              </button>
              <button
                onClick={() => setFilterMode('synced')}
                className={`px-3 py-1 rounded-lg transition-colors cursor-pointer ${
                  filterMode === 'synced' ? 'bg-white text-emerald-700 shadow-xs' : 'text-slate-500 hover:text-slate-800'
                }`}
              >
                Đã đủ ảnh ({syncedCount})
              </button>
            </div>
          </div>

          {/* Orders List */}
          {filteredOrders.length === 0 ? (
            <div className="py-8 text-center text-slate-400 text-xs">
              {searchQuery ? 'Không tìm thấy đơn hàng nào khớp với tìm kiếm.' : 'Không có đơn hàng nào trong Waiting.'}
            </div>
          ) : (
            <div className="space-y-2">
              {filteredOrders.map((order) => {
                const itemStatus = syncStatusMap[order.id] || { status: 'idle', count: order.image_count }
                const currentCount = itemStatus.count ?? order.image_count

                return (
                  <div
                    key={order.id}
                    className={`p-3 rounded-xl border flex items-center justify-between gap-3 transition-colors text-xs ${
                      itemStatus.status === 'syncing'
                        ? 'bg-purple-50/70 border-purple-300 ring-2 ring-purple-500/20'
                        : 'bg-white border-slate-200 hover:bg-slate-50/80'
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      {order.thumbnail_url ? (
                        <img
                          src={order.thumbnail_url}
                          alt={order.external_order_id}
                          className="w-10 h-10 rounded-lg object-cover border border-slate-200 shrink-0"
                        />
                      ) : (
                        <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center text-slate-400 font-bold shrink-0">
                          DJ
                        </div>
                      )}
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-slate-800 font-mono">{order.external_order_id}</span>
                          <span
                            className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              currentCount > 1
                                ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                : 'bg-amber-50 text-amber-700 border border-amber-200'
                            }`}
                          >
                            {currentCount} ảnh
                          </span>
                          {itemStatus.status === 'pending' && (
                            <span className="text-[10px] text-purple-600 bg-purple-50 px-1.5 py-0.2 rounded border border-purple-200">
                              Đang chờ trong hàng đợi...
                            </span>
                          )}
                        </div>
                        <p className="text-slate-500 truncate text-[11px] max-w-sm" title={order.product_name || ''}>
                          {order.product_name || 'Không có tên'}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      {order.sales_url && (
                        <a
                          href={order.sales_url}
                          target="_blank"
                          rel="noreferrer"
                          className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100"
                          title="Xem trang sản phẩm"
                        >
                          <ExternalLink className="h-4 w-4" />
                        </a>
                      )}

                      {/* Action / Priority Retry Button */}
                      {itemStatus.status === 'syncing' ? (
                        <span className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[11px] font-bold bg-purple-100 text-purple-800 border border-purple-300">
                          <Loader2 className="h-3 w-3 animate-spin" /> Đang quét...
                        </span>
                      ) : itemStatus.status === 'success' ? (
                        <span className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-[11px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                          <Check className="h-3 w-3 text-emerald-600" /> Đã lấy {itemStatus.count} ảnh
                        </span>
                      ) : itemStatus.status === 'error' ? (
                        <button
                          type="button"
                          onClick={() => prioritizeOrder(order)}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-[11px] font-bold bg-rose-50 text-rose-700 border border-rose-200 hover:bg-rose-100 cursor-pointer shadow-2xs transition-all hover:scale-102"
                          title={`Lỗi: ${itemStatus.error || 'Thử lại'}. Bấm để ưu tiên thử lại ngay đơn này!`}
                        >
                          <ArrowUpCircle className="h-3.5 w-3.5 text-rose-600" />
                          <span>Ưu tiên thử lại</span>
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => prioritizeOrder(order)}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-[11px] font-bold bg-slate-100 text-slate-700 hover:bg-slate-200 border border-slate-200 cursor-pointer shadow-2xs transition-all hover:scale-102"
                          title="Ưu tiên đồng bộ ngay đơn này"
                        >
                          <ArrowUpCircle className="h-3.5 w-3.5 text-slate-500" />
                          <span>Ưu tiên đồng bộ</span>
                        </button>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-slate-100 bg-slate-50 flex items-center justify-between text-xs text-slate-500">
          <span>* Bộ ảnh sẽ tự động đồng bộ sang giao diện Designer sau khi quét xong</span>
          <button
            onClick={closeModal}
            className="px-4 py-1.5 rounded-xl font-bold bg-slate-200 hover:bg-slate-300 text-slate-700 transition-colors cursor-pointer"
          >
            Đóng
          </button>
        </div>
      </div>
    </div>
  )
}
