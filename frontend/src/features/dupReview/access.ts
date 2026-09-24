import { ApiError, apiFetch, apiFetchBlob } from '../../api/client'

// The hidden review area has its own password. Unlocking gives a token the web keeps for this
// browser session; it is sent with every review request and dies with the tab or a password change.
const TOKEN_KEY = 'dupreview.token'
export const LOCKED_EVENT = 'dupreview-locked'

export function getReviewToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setReviewToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    // storage blocked: the area then asks for the password on every load
  }
}

function tokenHeader(): Record<string, string> {
  const token = getReviewToken()
  return token ? { 'X-Review-Token': token } : {}
}

function lockedOut(e: unknown): boolean {
  return e instanceof ApiError && e.status === 403 && typeof e.detail === 'object' && e.detail !== null && (e.detail as { code?: string }).code === 'review_locked'
}

function relock(e: unknown): never {
  if (lockedOut(e)) {
    setReviewToken(null)
    window.dispatchEvent(new Event(LOCKED_EVENT))
  }
  throw e
}

/** apiFetch with the review token; a "locked" answer sends the UI back to the password screen. */
export async function reviewFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  try {
    return await apiFetch<T>(path, { ...init, headers: { ...(init.headers as Record<string, string> | undefined), ...tokenHeader() } })
  } catch (e) {
    return relock(e)
  }
}

export async function reviewBlob(path: string): Promise<Blob> {
  try {
    return await apiFetchBlob(path, tokenHeader())
  } catch (e) {
    return relock(e)
  }
}

export interface AccessState {
  has_password: boolean
  unlocked: boolean
}

const BASE = '/support-review/access'

export const fetchAccess = () => reviewFetch<AccessState>(BASE)

async function withToken(request: Promise<{ token: string }>): Promise<void> {
  const { token } = await request
  setReviewToken(token)
}

export const setupPassword = (password: string) =>
  withToken(apiFetch<{ token: string }>(`${BASE}/setup`, { method: 'POST', body: JSON.stringify({ password }) }))

export const unlockReview = (password: string) =>
  withToken(apiFetch<{ token: string }>(`${BASE}/unlock`, { method: 'POST', body: JSON.stringify({ password }) }))

export const changePassword = (current_password: string, new_password: string) =>
  withToken(reviewFetch<{ token: string }>(`${BASE}/change`, { method: 'POST', body: JSON.stringify({ current_password, new_password }) }))
