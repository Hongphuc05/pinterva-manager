export class ApiError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail: unknown = message) {
    super(message)
    this.status = status
    this.detail = detail
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = localStorage.getItem('token')
  const activePlatformId = localStorage.getItem('activePlatformId')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init?.headers as Record<string, string> ?? {}),
  }
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }
  if (activePlatformId) {
    headers['X-Platform-Id'] = activePlatformId
  }

  const baseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
  const resp = await fetch(`${baseUrl}/api${path}`, {
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
    throw new ApiError(resp.status, message, detail)
  }
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}

export function resolveAssetUrl(url: string | null | undefined): string {
  if (!url) return ''
  if (url.startsWith('/crawled_assets/') || url.startsWith('/order_assets/')) {
    const baseUrl = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')
    return baseUrl ? `${baseUrl}${url}` : url
  }
  return url
}
