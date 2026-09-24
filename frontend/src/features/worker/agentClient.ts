// The Support agent on this machine listens on localhost; the web page talks to it directly.
export const AGENT_URL: string = import.meta.env.VITE_AGENT_URL || 'http://127.0.0.1:8765'
const TIMEOUT_MS = 2500

export type AgentState = 'waiting' | 'ready' | 'busy' | 'paused'

export interface AgentStatus {
  agent: string
  version: number
  name: string
  state: AgentState
  device: string | null
  model_loaded: boolean
}

async function call(path: string, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)
  try {
    // targetAddressSpace tells Chrome this is a loopback request (Local Network Access permission).
    return await fetch(`${AGENT_URL}${path}`, { ...init, signal: controller.signal, targetAddressSpace: 'loopback' } as RequestInit)
  } finally {
    clearTimeout(timer)
  }
}

/** The agent's status, or null when no agent answers on this machine. */
export async function probeAgent(): Promise<AgentStatus | null> {
  try {
    const res = await call('/status')
    if (!res.ok) return null
    const body = (await res.json()) as AgentStatus
    return body?.agent === 'support-compare' ? body : null
  } catch {
    return null
  }
}

/** Hand the agent the token that lets this machine compute during this login. */
export async function connectAgent(token: string): Promise<AgentStatus> {
  const res = await call('/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token }),
  })
  if (!res.ok) throw new Error('Agent từ chối kết nối')
  return (await res.json()) as AgentStatus
}

export async function disconnectAgent(): Promise<void> {
  try {
    await call('/disconnect', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
  } catch {
    // the agent stops by itself when the token is revoked
  }
}
