import { useEffect } from 'react'
import { useAuth } from '../../auth/AuthContext'
import { sendPresence } from './api'

const INTERVAL_MS = 20_000

/**
 * While a Support has the web open, tell the API so the machines they allowed may compute.
 * Closing the tab or logging out stops the beats; the API then pauses those machines within ~90 s.
 */
export function useWorkerPresence() {
  const { user } = useAuth()
  const allowed = user?.role === 'support'
  useEffect(() => {
    if (!allowed) return
    const beat = () => void sendPresence().catch(() => undefined)
    beat()
    const timer = setInterval(beat, INTERVAL_MS)
    const onVisible = () => document.visibilityState === 'visible' && beat()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [allowed])
}
