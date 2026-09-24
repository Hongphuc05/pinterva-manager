import { useCallback, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'

export const SECRET_PATH = '/duplicate-review'
const CLICKS_NEEDED = 5
const CLICK_WINDOW_MS = 3000

/**
 * Hidden ways into the review area for Support (it has no menu entry; the password still applies):
 * the keyboard shortcut Alt+Shift+D (Option+Shift+D on a Mac), or five quick clicks on the logo.
 */
export function useSecretEntry() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const enabled = user?.role === 'support'
  const clicks = useRef<number[]>([])

  useEffect(() => {
    if (!enabled) return
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(tag ?? '')) return
      if (e.altKey && e.shiftKey && !e.ctrlKey && !e.metaKey && e.code === 'KeyD') {
        e.preventDefault()
        navigate(SECRET_PATH)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [enabled, navigate])

  const onLogoClick = useCallback(() => {
    if (!enabled) return
    const now = Date.now()
    clicks.current = [...clicks.current.filter((t) => now - t < CLICK_WINDOW_MS), now]
    if (clicks.current.length >= CLICKS_NEEDED) {
      clicks.current = []
      navigate(SECRET_PATH)
    }
  }, [enabled, navigate])

  return { onLogoClick }
}
