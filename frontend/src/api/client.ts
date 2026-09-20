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
    let message = resp.statusText
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
  return resp.json() as Promise<T>
}

/** Fetch a private binary asset with the same bearer/platform credentials as API data. */
export async function apiFetchBlob(path: string): Promise<Blob> {
  const token = localStorage.getItem('token')
  const activePlatformId = localStorage.getItem('activePlatformId')
  const headers: Record<string, string> = {}
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
