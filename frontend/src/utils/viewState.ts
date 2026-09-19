const STORAGE_PREFIX = 'tacahu:view-state:v1'

function storageKey(view: string, role?: string | null) {
  return `${STORAGE_PREFIX}:${view}:${role || 'unknown'}`
}

/**
 * UI state is deliberately kept client-side. It contains only navigation,
 * filters and display preferences; it never stores order data or form drafts.
 */
export function readViewState<T extends Record<string, unknown>>(
  view: string,
  role: string | null | undefined,
  fallback: T,
): T {
  try {
    const raw = localStorage.getItem(storageKey(view, role))
    if (!raw) return fallback
    const stored = JSON.parse(raw)
    if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return fallback
    return { ...fallback, ...stored }
  } catch {
    return fallback
  }
}

export function writeViewState<T extends Record<string, unknown>>(
  view: string,
  role: string | null | undefined,
  value: T,
) {
  try {
    localStorage.setItem(storageKey(view, role), JSON.stringify(value))
  } catch {
    // Storage can be unavailable (private mode/quota). The page must still work.
  }
}
