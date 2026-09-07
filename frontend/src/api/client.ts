export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    ...init,
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (resp.status === 401 && !path.startsWith('/me') && !path.startsWith('/login')) {
    window.location.assign('/login')
    // Never resolves — the redirect is already in flight; the caller doesn't need
    // a value it won't render before the navigation completes.
    return new Promise<T>(() => {})
  }
  if (!resp.ok) {
    let message = resp.statusText
    try {
      const body = await resp.json()
      message = body.detail ?? message
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(resp.status, message)
  }
  if (resp.status === 204) return undefined as T
  return resp.json() as Promise<T>
}
