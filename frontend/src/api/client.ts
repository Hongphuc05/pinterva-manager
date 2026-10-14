export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail: unknown = message) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

/**
 * The API helpers own the `/api` prefix. Normalize a configured base URL so
 * deployments may use either `https://example.com` or `https://example.com/api`
 * without accidentally requesting `/api/api/...`.
 */
function getApiBaseUrl(): string {
  const configured = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/+$/, '')
  return configured.replace(/(?:\/api)+$/, '')
}

function getApiUrl(path: string): string {
  // Most client calls use a route such as `/orders`. Some API responses, including
  // private work-note attachment URLs, already return their canonical `/api/...` path.
  // Normalize both forms so the client never asks for `/api/api/...`.
  const route = path.startsWith('/api/') ? path.slice('/api'.length) : path
  return `${getApiBaseUrl()}/api${route.startsWith('/') ? route : `/${route}`}`
}

type OrderVersionConflictDetail = {
  code: 'ORDER_VERSION_CONFLICT'
  message?: string
  order_id?: string | null
  expected_version?: number | null
  current_version?: number | null
  changed_fields?: string[]
}

function publishOrderVersionConflict(detail: unknown) {
  if (typeof window === 'undefined' || !detail || typeof detail !== 'object') return
  const conflict = detail as OrderVersionConflictDetail
  if (conflict.code !== 'ORDER_VERSION_CONFLICT') return

  const message = conflict.message || 'Đơn vừa được cập nhật bởi người khác. Dữ liệu mới đã được tải lại.'
  window.dispatchEvent(new CustomEvent('order-version-conflict', { detail: conflict }))
  window.dispatchEvent(new CustomEvent('orders-updated'))
  window.dispatchEvent(new CustomEvent('app-toast', {
    detail: { message, type: 'warning', duration: 7000 },
  }))
}

// Last successful GET response per (user, platform, path), kept in memory so a page that is
// opened again can paint at once while it refreshes in the background (see peekApi).
const API_CACHE_MAX = 80
// Shared by peekApi and by pages that cache their own view (e.g. the order list pages).
export const memoryCache = new Map<string, unknown>()
const apiCache = memoryCache

function apiCacheKey(path: string) {
  const token = localStorage.getItem('token') || ''
  return `${token.slice(-24)}|${localStorage.getItem('activePlatformId') || ''}|${path}`
}

/** The last response of `GET path` this session, or undefined. Always refetch after using it. */
export function peekApi<T>(path: string): T | undefined {
  return apiCache.get(apiCacheKey(path)) as T | undefined
}

export function clearApiCache() {
  apiCache.clear()
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('token')
  const activePlatformId = localStorage.getItem('activePlatformId')
  const headers: Record<string, string> = {
    ...(init?.headers as Record<string, string> ?? {}),
  }
  // The browser must provide the multipart boundary for clipboard/file uploads.
  if (!(init?.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json'
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  if (activePlatformId) {
    headers['X-Platform-Id'] = activePlatformId
  }

  const baseUrl = getApiBaseUrl()
  const resp = await fetch(getApiUrl(path), {
    ...init,
    credentials: baseUrl ? 'include' : 'same-origin',
    headers,
  })
  if (resp.status === 401 && !path.startsWith('/me') && !path.startsWith('/login')) {
    window.location.assign('/login')
    // Never resolves — the redirect is already in flight; the caller doesn't need
    // a value it won't render before the navigation completes.
    return new Promise<T>(() => {})
  }
  if (!resp.ok) {
    // resp.statusText is often empty over HTTP/2 (e.g. through Cloudflare Tunnel in
    // production) — never let the fallback end up as a literally blank error message.
    let message = resp.statusText || `Lỗi máy chủ (HTTP ${resp.status})`
    let detail: unknown = undefined
    try {
      const body = await resp.json()
      detail = body.detail
      const detailMessage =
        typeof detail === 'object' && detail !== null && 'message' in detail && typeof detail.message === 'string'
          ? detail.message
          : undefined
      message = typeof detail === 'string' ? detail : detailMessage ?? message
    } catch {
      // response wasn't JSON — keep statusText
    }
    publishOrderVersionConflict(detail)
    throw new ApiError(resp.status, message, detail)
  }
  if (resp.status === 204) return undefined as T
  const data = (await resp.json()) as T
  if (!init?.method || init.method.toUpperCase() === 'GET') {
    const key = apiCacheKey(path)
    apiCache.delete(key)
    apiCache.set(key, data)
    while (apiCache.size > API_CACHE_MAX) apiCache.delete(apiCache.keys().next().value as string)
  }
  return data
}

/** Fetch a private binary asset with the same bearer/platform credentials as API data. */
export async function apiFetchBlob(path: string, extraHeaders: Record<string, string> = {}): Promise<Blob> {
  const token = localStorage.getItem('token')
  const activePlatformId = localStorage.getItem('activePlatformId')
  const headers: Record<string, string> = { ...extraHeaders }
  if (token) headers.Authorization = `Bearer ${token}`
  if (activePlatformId) headers['X-Platform-Id'] = activePlatformId

  const baseUrl = getApiBaseUrl()
  const resp = await fetch(getApiUrl(path), {
    credentials: baseUrl ? 'include' : 'same-origin',
    headers,
  })
  if (resp.status === 401) {
    window.location.assign('/login')
    return new Promise<Blob>(() => {})
  }
  if (!resp.ok) throw new ApiError(resp.status, resp.statusText)
  return resp.blob()
}

export function resolveAssetUrl(url: string | null | undefined): string {
  if (!url) return ''
  if (url.startsWith('/crawled_assets/') || url.startsWith('/order_assets/') || url.startsWith('/api/')) {
    const baseUrl = getApiBaseUrl()
    return baseUrl ? `${baseUrl}${url}` : url
  }
  return url
}
