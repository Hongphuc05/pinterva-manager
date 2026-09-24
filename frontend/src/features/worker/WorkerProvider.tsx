import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { apiFetch } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../../context/ToastContext'
import { connectAgent, disconnectAgent, probeAgent, type AgentStatus } from './agentClient'

const PRESENCE_MS = 20_000
const PROBE_MS = 8_000
const MAX_AUTO_FAILURES = 3

export type Consent = 'yes' | 'no' | null

interface WorkerContextValue {
  /** Status of the agent on this machine, null when none answers. */
  agent: AgentStatus | null
  /** True once the first probe finished. */
  probed: boolean
  consent: Consent
  busy: boolean
  /** The user said "Có": grant this machine and hand the agent its token. */
  allow: () => Promise<void>
  /** The user said "Không" (this login only). */
  decline: () => void
  /** Stop this machine: revoke its grant and disconnect the agent. */
  stop: () => Promise<void>
}

const WorkerContext = createContext<WorkerContextValue | null>(null)

export function useWorker(): WorkerContextValue {
  const ctx = useContext(WorkerContext)
  if (!ctx) throw new Error('useWorker must be used inside WorkerProvider')
  return ctx
}

// The answer is remembered per login: a new login (new session token) is asked again.
const sessionKey = () => (localStorage.getItem('token') ?? '').slice(-16)
const consentKey = () => `worker.consent.${sessionKey()}`
const deviceKey = () => `worker.device.${sessionKey()}`

function readConsent(): Consent {
  try {
    const value = sessionStorage.getItem(consentKey())
    return value === 'yes' || value === 'no' ? value : null
  } catch {
    return null
  }
}

/**
 * For Support only: keeps this login's machines allowed (presence heartbeat), finds the agent on
 * this machine, asks "Có/Không" once per login and hands the agent its token.
 */
export function WorkerProvider({ children, ConsentDialog }: { children: ReactNode; ConsentDialog?: React.ComponentType }) {
  const { user } = useAuth()
  const { showToast } = useToast()
  const isSupport = user?.role === 'support'
  const [agent, setAgent] = useState<AgentStatus | null>(null)
  const [probed, setProbed] = useState(false)
  const [consent, setConsent] = useState<Consent>(readConsent)
  const [busy, setBusy] = useState(false)
  const granting = useRef(false)
  const failures = useRef(0)
  const agentRef = useRef<AgentStatus | null>(null)
  useEffect(() => {
    agentRef.current = agent
  }, [agent])

  const refresh = useCallback(async () => {
    const status = await probeAgent()
    setAgent(status)
    setProbed(true)
    return status
  }, [])

  // Presence: tells the API the web is open, so this login's machines may compute.
  useEffect(() => {
    if (!isSupport) return
    const beat = () => void apiFetch('/support-worker/presence', { method: 'POST' }).catch(() => undefined)
    beat()
    const timer = setInterval(beat, PRESENCE_MS)
    const onVisible = () => document.visibilityState === 'visible' && beat()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [isSupport])

  // Look for the agent on this machine.
  useEffect(() => {
    if (!isSupport) return
    void refresh()
    const timer = setInterval(() => void refresh(), PROBE_MS)
    return () => clearInterval(timer)
  }, [isSupport, refresh])

  // A new login starts with a fresh question.
  useEffect(() => {
    if (isSupport) setConsent(readConsent())
    else setConsent(null)
  }, [isSupport, user?.id])

  // Logging out stops the machine at once (the API also revokes it).
  const wasSupport = useRef(false)
  useEffect(() => {
    if (wasSupport.current && !isSupport) void disconnectAgent()
    wasSupport.current = isSupport
  }, [isSupport])

  const grantAndConnect = useCallback(async (): Promise<boolean> => {
    const current = agentRef.current
    if (!current || granting.current) return false
    granting.current = true
    setBusy(true)
    try {
      const grant = await apiFetch<{ id: string; token: string }>('/support-worker/devices/grant', {
        method: 'POST',
        body: JSON.stringify({ machine_name: current.name }),
      })
      await connectAgent(grant.token)
      try {
        sessionStorage.setItem(deviceKey(), grant.id)
      } catch {
        // storage unavailable: Stop then only disconnects the agent
      }
      failures.current = 0
      await refresh()
      return true
    } catch {
      failures.current += 1
      return false
    } finally {
      granting.current = false
      setBusy(false)
    }
  }, [refresh])

  // Consent given earlier in this login but the agent lost its token (restarted): grant again quietly.
  useEffect(() => {
    if (isSupport && consent === 'yes' && agent?.state === 'waiting' && failures.current < MAX_AUTO_FAILURES) {
      void grantAndConnect()
    }
  }, [isSupport, consent, agent?.state, grantAndConnect])

  const remember = (value: Consent) => {
    try {
      if (value) sessionStorage.setItem(consentKey(), value)
    } catch {
      // ignore
    }
    setConsent(value)
  }

  const allow = useCallback(async () => {
    remember('yes')
    failures.current = 0
    const ok = await grantAndConnect()
    if (ok) showToast('Máy này đang chạy hàng đợi trong phiên đăng nhập của bạn.', 'success')
    else showToast('Không kết nối được với agent trên máy này.', 'error')
  }, [grantAndConnect, showToast])

  const decline = useCallback(() => remember('no'), [])

  const stop = useCallback(async () => {
    remember('no')
    let deviceId: string | null = null
    try {
      deviceId = sessionStorage.getItem(deviceKey())
    } catch {
      // ignore
    }
    if (deviceId) await apiFetch(`/support-worker/devices/${deviceId}/revoke`, { method: 'POST' }).catch(() => undefined)
    await disconnectAgent()
    await refresh()
  }, [refresh])

  const value = useMemo(
    () => ({ agent, probed, consent, busy, allow, decline, stop }),
    [agent, probed, consent, busy, allow, decline, stop],
  )
  const promptOpen = isSupport && agent?.state === 'waiting' && consent === null
  return (
    <WorkerContext.Provider value={value}>
      {children}
      {promptOpen && ConsentDialog ? <ConsentDialog /> : null}
    </WorkerContext.Provider>
  )
}
