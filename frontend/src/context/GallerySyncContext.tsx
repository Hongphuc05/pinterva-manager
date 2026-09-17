import React, { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import { apiFetch } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { usePlatform } from '../auth/PlatformContext'

export type PendingGalleryOrder = {
  id: string
  external_order_id: string
  product_name: string | null
  thumbnail_url: string | null
  sales_url: string | null
  image_count: number
}

export type OrderSyncItemStatus = {
  status: 'idle' | 'pending' | 'syncing' | 'success' | 'error'
  count?: number
  error?: string
}

export type GalleryProgress = {
  current: number
  total: number
  successCount: number
  currentOrderCode?: string
}

export type GallerySyncStats = {
  total: number
  processed: number
  successCount: number
  currentOrderCode?: string
}

type GallerySyncContextType = {
  isSyncing: boolean
  isPaused: boolean
  progress: GalleryProgress | null
  waitingOrders: PendingGalleryOrder[]
  syncStatusMap: Record<string, OrderSyncItemStatus>
  isModalOpen: boolean
  isExtensionConnected: boolean
  pendingWaitingCount: number
  totalWaitingCount: number
  openModal: () => void
  closeModal: () => void
  pauseSync: () => void
  resumeSync: () => void
  triggerSyncWaiting: (forceAll?: boolean) => Promise<void>
  loadWaitingOrders: () => Promise<PendingGalleryOrder[]>
  syncSingleOrder: (order: PendingGalleryOrder) => Promise<boolean>
  prioritizeOrder: (order: PendingGalleryOrder) => Promise<void>
}

const STORAGE_KEY_QUEUE = 'tacahu_gallery_sync_queue'
const STORAGE_KEY_STATS = 'tacahu_gallery_sync_stats'
const STORAGE_KEY_PAUSED = 'tacahu_gallery_sync_paused'
const STORAGE_KEY_STATUS_MAP = 'tacahu_gallery_sync_status_map'

function loadStoredQueue(): PendingGalleryOrder[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_QUEUE)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function loadStoredStats(): GallerySyncStats | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_STATS)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

function loadStoredPaused(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY_PAUSED) === 'true'
  } catch {
    return false
  }
}

function loadStoredStatusMap(): Record<string, OrderSyncItemStatus> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_STATUS_MAP)
    return raw ? JSON.parse(raw) : {}
  } catch {
    return {}
  }
}

const GallerySyncContext = createContext<GallerySyncContextType | undefined>(undefined)

export function GallerySyncProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth()
  const { activePlatform } = usePlatform()
  const isAdmin = user?.role === 'admin'

  const [waitingOrders, setWaitingOrders] = useState<PendingGalleryOrder[]>([])
  const [syncStatusMap, setSyncStatusMap] = useState<Record<string, OrderSyncItemStatus>>(() => loadStoredStatusMap())
  
  const initialQueue = loadStoredQueue()
  const initialStats = loadStoredStats()
  const initialPaused = loadStoredPaused()

  const [isSyncing, setIsSyncing] = useState<boolean>(initialQueue.length > 0)
  const [isPaused, setIsPaused] = useState<boolean>(initialPaused)
  const [progress, setProgress] = useState<GalleryProgress | null>(() => {
    if (initialStats && initialStats.total > 0 && initialQueue.length > 0) {
      return {
        current: initialStats.processed,
        total: initialStats.total,
        successCount: initialStats.successCount,
        currentOrderCode: initialStats.currentOrderCode,
      }
    }
    return null
  })

  const [isModalOpen, setIsModalOpen] = useState(false)
  const [isExtensionConnected, setIsExtensionConnected] = useState(false)

  const queueRef = useRef<PendingGalleryOrder[]>(initialQueue)
  const statsRef = useRef<GallerySyncStats>(initialStats || { total: 0, processed: 0, successCount: 0 })
  const isPausedRef = useRef<boolean>(initialPaused)
  const isProcessingRef = useRef<boolean>(false)
  const syncStatusMapRef = useRef<Record<string, OrderSyncItemStatus>>(syncStatusMap)

  // Keep ref in sync
  useEffect(() => {
    syncStatusMapRef.current = syncStatusMap
    try {
      localStorage.setItem(STORAGE_KEY_STATUS_MAP, JSON.stringify(syncStatusMap))
    } catch {}
  }, [syncStatusMap])

  // Extension ping/pong listener
  useEffect(() => {
    function handleMsg(e: MessageEvent) {
      if (e.data?.type === 'TACAHU_PONG' || e.data?.type === 'TACAHU_EXTENSION_READY') {
        setIsExtensionConnected(true)
      }
    }
    window.addEventListener('message', handleMsg)
    window.postMessage({ type: 'TACAHU_PING' }, '*')

    const interval = setInterval(() => {
      window.postMessage({ type: 'TACAHU_PING' }, '*')
    }, 2500)

    return () => {
      window.removeEventListener('message', handleMsg)
      clearInterval(interval)
    }
  }, [])

  function fetchGalleryViaBridge(orderId: string, salesUrl: string): Promise<string[]> {
    return new Promise((resolve, reject) => {
      let isSettled = false

      const timeout = setTimeout(() => {
        if (!isSettled) {
          isSettled = true
          window.removeEventListener('message', onMessage)
          reject(new Error('Extension không phản hồi trong 28s'))
        }
      }, 28000)

      function onMessage(e: MessageEvent) {
        if (e.data?.type === 'TACAHU_GALLERY_RESPONSE' && e.data?.orderId === orderId) {
          if (!isSettled) {
            isSettled = true
            clearTimeout(timeout)
            window.removeEventListener('message', onMessage)
            if (e.data?.success && Array.isArray(e.data?.images) && e.data.images.length > 0) {
              resolve(e.data.images)
            } else {
              reject(new Error(e.data?.error || 'Không bóc tách được ảnh sản phẩm từ trang'))
            }
          }
        }
      }

      window.addEventListener('message', onMessage)
      window.postMessage(
        {
          type: 'TACAHU_FETCH_GALLERY_REQUEST',
          orderId,
          salesUrl,
        },
        '*'
      )
    })
  }

  const executeSyncSingleOrder = useCallback(async (order: PendingGalleryOrder): Promise<boolean> => {
    setSyncStatusMap((prev) => ({ ...prev, [order.id]: { status: 'syncing' } }))

    // 1. Primary: Server Playwright scraper
    try {
      const res = await apiFetch<{ ok: boolean; image_count: number }>(`/orders/${order.id}/sync-gallery`, {
        method: 'POST',
      })
      if (res.ok && res.image_count > 0) {
        setSyncStatusMap((prev) => ({ ...prev, [order.id]: { status: 'success', count: res.image_count } }))
        return true
      }
    } catch (serverErr) {
      console.warn('Server sync attempt finished, checking bridge...', serverErr)
    }

    // 2. Secondary: Fallback to Extension bridge if server scraper encountered Cloudflare or page error
    if (order.sales_url) {
      try {
        const imageUrls = await fetchGalleryViaBridge(order.external_order_id, order.sales_url)
        if (imageUrls && imageUrls.length > 0) {
          const res = await apiFetch<{ ok: boolean; image_count: number }>(`/orders/${order.id}/gallery`, {
            method: 'PATCH',
            body: JSON.stringify({ image_urls: imageUrls, product_url: order.sales_url }),
          })
          setSyncStatusMap((prev) => ({ ...prev, [order.id]: { status: 'success', count: res.image_count } }))
          return true
        }
      } catch (bridgeErr: any) {
        setSyncStatusMap((prev) => ({
          ...prev,
          [order.id]: { status: 'error', error: bridgeErr?.message || 'Không bóc tách được ảnh' },
        }))
        return false
      }
    }

    setSyncStatusMap((prev) => ({ ...prev, [order.id]: { status: 'error', error: 'Không bóc tách được ảnh' } }))
    return false
  }, [])

  const loadWaitingOrders = useCallback(async (): Promise<PendingGalleryOrder[]> => {
    if (!isAdmin) return []
    try {
      const res = await apiFetch<{ orders: PendingGalleryOrder[] }>('/orders/pending-galleries?state=waiting')
      const list = res.orders || []
      setWaitingOrders(list)
      setSyncStatusMap((prev) => {
        const next = { ...prev }
        list.forEach((o) => {
          if (!next[o.id]) {
            next[o.id] = { status: o.image_count > 1 ? 'success' : 'idle', count: o.image_count }
          }
        })
        return next
      })
      return list
    } catch {
      return []
    }
  }, [isAdmin])

  // Process queue worker loop
  const processQueue = useCallback(async () => {
    if (isProcessingRef.current) return
    isProcessingRef.current = true
    setIsSyncing(true)

    try {
      while (queueRef.current.length > 0) {
        if (isPausedRef.current) {
          isProcessingRef.current = false
          return
        }

        const nextOrder = queueRef.current.shift()!
        localStorage.setItem(STORAGE_KEY_QUEUE, JSON.stringify(queueRef.current))

        const currentProcessed = statsRef.current.processed
        const total = statsRef.current.total
        const successCount = statsRef.current.successCount

        const currentProg: GalleryProgress = {
          current: Math.min(currentProcessed + 1, total),
          total,
          successCount,
          currentOrderCode: nextOrder.external_order_id,
        }
        setProgress(currentProg)

        localStorage.setItem(
          STORAGE_KEY_STATS,
          JSON.stringify({
            total,
            processed: currentProcessed,
            successCount,
            currentOrderCode: nextOrder.external_order_id,
          })
        )

        const ok = await executeSyncSingleOrder(nextOrder)

        statsRef.current.processed += 1
        if (ok) {
          statsRef.current.successCount += 1
        }

        localStorage.setItem(STORAGE_KEY_STATS, JSON.stringify(statsRef.current))

        setProgress({
          current: statsRef.current.processed,
          total: statsRef.current.total,
          successCount: statsRef.current.successCount,
        })
      }

      // All items completed
      isProcessingRef.current = false
      setIsSyncing(false)
      setProgress(null)

      localStorage.removeItem(STORAGE_KEY_QUEUE)
      localStorage.removeItem(STORAGE_KEY_STATS)
      localStorage.removeItem(STORAGE_KEY_PAUSED)

      const finalSuccess = statsRef.current.successCount
      const finalTotal = statsRef.current.total

      if (finalTotal > 0) {
        window.dispatchEvent(
          new CustomEvent('gallery-sync-notify', {
            detail: {
              type: 'success',
              message: `Đã hoàn tất đồng bộ ảnh: ${finalSuccess}/${finalTotal} đơn thành công!`,
            },
          })
        )
        window.dispatchEvent(new CustomEvent('orders-updated'))
        loadWaitingOrders().catch(() => {})
      }
    } finally {
      isProcessingRef.current = false
    }
  }, [executeSyncSingleOrder, loadWaitingOrders])

  // Pause queue execution
  const pauseSync = useCallback(() => {
    isPausedRef.current = true
    setIsPaused(true)
    localStorage.setItem(STORAGE_KEY_PAUSED, 'true')
  }, [])

  // Resume queue execution
  const resumeSync = useCallback(() => {
    isPausedRef.current = false
    setIsPaused(false)
    localStorage.setItem(STORAGE_KEY_PAUSED, 'false')
    if (queueRef.current.length > 0) {
      processQueue()
    }
  }, [processQueue])

  // Priority Retry / Sync: Inserts target order at index 0 of queue and triggers processing
  const prioritizeOrder = useCallback(
    async (order: PendingGalleryOrder) => {
      // 1. Remove if already exists in queue
      queueRef.current = queueRef.current.filter((o) => o.id !== order.id)
      // 2. Put at the very front (index 0)
      queueRef.current.unshift(order)
      localStorage.setItem(STORAGE_KEY_QUEUE, JSON.stringify(queueRef.current))

      // 3. Mark as pending in UI
      setSyncStatusMap((prev) => ({ ...prev, [order.id]: { status: 'pending', count: order.image_count } }))

      // 4. Update stats
      if (statsRef.current.total === 0 || !isSyncing) {
        statsRef.current = {
          total: queueRef.current.length,
          processed: 0,
          successCount: 0,
        }
      } else {
        statsRef.current.total = Math.max(statsRef.current.total, statsRef.current.processed + queueRef.current.length)
      }
      localStorage.setItem(STORAGE_KEY_STATS, JSON.stringify(statsRef.current))

      // 5. Unpause if paused
      if (isPausedRef.current) {
        isPausedRef.current = false
        setIsPaused(false)
        localStorage.setItem(STORAGE_KEY_PAUSED, 'false')
      }

      setIsSyncing(true)
      processQueue()
    },
    [isSyncing, processQueue]
  )

  const syncSingleOrder = useCallback(
    async (order: PendingGalleryOrder): Promise<boolean> => {
      await prioritizeOrder(order)
      return true
    },
    [prioritizeOrder]
  )

  const triggerSyncWaiting = useCallback(
    async (forceAll = false) => {
      if (isSyncing && queueRef.current.length > 0) {
        setIsModalOpen(true)
        return
      }

      // 1. Refresh waiting orders list from backend
      const latestWaiting = await loadWaitingOrders()
      if (latestWaiting.length === 0) {
        window.dispatchEvent(
          new CustomEvent('gallery-sync-notify', {
            detail: { type: 'info', message: 'Không có đơn hàng nào trong tab Waiting để đồng bộ ảnh.' },
          })
        )
        return
      }

      // 2. Filter candidate orders: Only sync orders that DO NOT yet have full gallery (> 1 image)
      const candidates = latestWaiting.filter((o) => {
        if (forceAll) return true
        const existingCount = syncStatusMap[o.id]?.count ?? o.image_count
        return existingCount <= 1
      })

      if (candidates.length === 0) {
        window.dispatchEvent(
          new CustomEvent('gallery-sync-notify', {
            detail: {
              type: 'info',
              message: `Tất cả ${latestWaiting.length} đơn trong Waiting đều đã có đủ bộ ảnh!`,
            },
          })
        )
        return
      }

      // 3. Mark candidate orders as pending in map
      setSyncStatusMap((prev) => {
        const next = { ...prev }
        candidates.forEach((o) => {
          next[o.id] = { status: 'pending', count: o.image_count }
        })
        return next
      })

      // 4. Initialize Queue and Stats
      queueRef.current = [...candidates]
      statsRef.current = { total: candidates.length, processed: 0, successCount: 0 }
      isPausedRef.current = false
      setIsPaused(false)

      localStorage.setItem(STORAGE_KEY_QUEUE, JSON.stringify(queueRef.current))
      localStorage.setItem(STORAGE_KEY_STATS, JSON.stringify(statsRef.current))
      localStorage.setItem(STORAGE_KEY_PAUSED, 'false')

      setIsSyncing(true)
      setProgress({ current: 0, total: candidates.length, successCount: 0 })

      processQueue()
    },
    [isSyncing, loadWaitingOrders, processQueue, syncStatusMap]
  )

  // Mount & F5 recovery effect
  useEffect(() => {
    if (isAdmin && activePlatform?.id) {
      loadWaitingOrders().catch(() => {})
    }

    // Check if there is an existing queue to resume after F5
    if (queueRef.current.length > 0) {
      setIsSyncing(true)
      if (!isPausedRef.current) {
        processQueue()
      }
    }
  }, [isAdmin, activePlatform?.id, loadWaitingOrders, processQueue])

  const pendingWaitingCount = waitingOrders.filter(
    (o) => (syncStatusMap[o.id]?.count ?? o.image_count) <= 1
  ).length

  return (
    <GallerySyncContext.Provider
      value={{
        isSyncing,
        isPaused,
        progress,
        waitingOrders,
        syncStatusMap,
        isModalOpen,
        isExtensionConnected,
        pendingWaitingCount,
        totalWaitingCount: waitingOrders.length,
        openModal: () => setIsModalOpen(true),
        closeModal: () => setIsModalOpen(false),
        pauseSync,
        resumeSync,
        triggerSyncWaiting,
        loadWaitingOrders,
        syncSingleOrder,
        prioritizeOrder,
      }}
    >
      {children}
    </GallerySyncContext.Provider>
  )
}

export function useGallerySync() {
  const context = useContext(GallerySyncContext)
  if (!context) {
    throw new Error('useGallerySync must be used within a GallerySyncProvider')
  }
  return context
}
