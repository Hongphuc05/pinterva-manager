import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ConsentDialog } from './ConsentDialog'
import type { AgentStatus } from './agentClient'
import { useWorker, WorkerProvider } from './WorkerProvider'

const auth = vi.hoisted(() => ({ user: null as null | { id: string; role: string } }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: auth.user }) }))
const toast = vi.hoisted(() => ({ showToast: vi.fn() }))
vi.mock('../../context/ToastContext', () => ({ useToast: () => toast }))
const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../../api/client', () => ({ apiFetch: api.apiFetch }))
const agentApi = vi.hoisted(() => ({ probeAgent: vi.fn(), connectAgent: vi.fn(), disconnectAgent: vi.fn() }))
vi.mock('./agentClient', () => agentApi)

const status = (over: Partial<AgentStatus> = {}): AgentStatus => ({ agent: 'support-compare', version: 1, name: 'MacBook Phúc', state: 'waiting', device: 'mps', model_loaded: true, ...over })

let current: AgentStatus | null
let calls: { path: string; init?: RequestInit }[]

function Probe() {
  const { consent, agent, stop } = useWorker()
  return (
    <div>
      <span data-testid="consent">{String(consent)}</span>
      <span data-testid="state">{agent?.state ?? 'none'}</span>
      <button onClick={() => void stop()}>stop</button>
    </div>
  )
}

const renderProvider = () =>
  render(
    <WorkerProvider ConsentDialog={ConsentDialog}>
      <Probe />
    </WorkerProvider>,
  )

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  localStorage.setItem('token', 'session-token-abcdef123456')
  auth.user = { id: 'u1', role: 'support' }
  current = status()
  calls = []
  toast.showToast.mockReset()
  api.apiFetch.mockReset().mockImplementation((path: string, init?: RequestInit) => {
    calls.push({ path, init })
    if (path === '/support-worker/devices/grant') return Promise.resolve({ id: 'dev1', token: 'sw_secret' })
    return Promise.resolve({ devices: [] })
  })
  agentApi.probeAgent.mockReset().mockImplementation(() => Promise.resolve(current))
  agentApi.connectAgent.mockReset().mockImplementation(async () => {
    current = status({ state: 'ready' })
    return current
  })
  agentApi.disconnectAgent.mockReset().mockImplementation(async () => {
    current = status({ state: 'waiting' })
  })
})
afterEach(() => vi.restoreAllMocks())

const granted = () => calls.filter((c) => c.path === '/support-worker/devices/grant')

describe('worker consent', () => {
  it('asks once when a Support logs in on a machine that runs the agent', async () => {
    renderProvider()
    expect(await screen.findByRole('dialog', { name: 'Cho phép dùng máy này' })).toHaveTextContent('MacBook Phúc')
    expect(granted()).toHaveLength(0) // nothing is granted before the answer
  })

  it('"Có" grants this machine from the session and hands the token to the agent', async () => {
    renderProvider()
    await userEvent.click(await screen.findByRole('button', { name: 'Có' }))
    await waitFor(() => expect(agentApi.connectAgent).toHaveBeenCalledWith('sw_secret'))
    expect(granted()[0].init?.body).toBe(JSON.stringify({ machine_name: 'MacBook Phúc' }))
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('ready'))
    expect(screen.getByTestId('consent')).toHaveTextContent('yes')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(toast.showToast).toHaveBeenCalledWith(expect.stringContaining('đang chạy hàng đợi'), 'success')
  })

  it('"Không" grants nothing and does not ask again in this login', async () => {
    const view = renderProvider()
    await userEvent.click(await screen.findByRole('button', { name: 'Không' }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(granted()).toHaveLength(0)
    view.unmount()
    renderProvider() // same login (page reload): the answer is remembered
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('waiting'))
    expect(screen.getByTestId('consent')).toHaveTextContent('no')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('a new login asks again', async () => {
    const first = renderProvider()
    await userEvent.click(await screen.findByRole('button', { name: 'Không' }))
    first.unmount()
    localStorage.setItem('token', 'another-session-token-zzzzzz')
    renderProvider()
    expect(await screen.findByRole('dialog')).toBeInTheDocument()
  })

  it('grants again by itself when the agent restarted during a login that already said yes', async () => {
    const view = renderProvider()
    await userEvent.click(await screen.findByRole('button', { name: 'Có' }))
    await waitFor(() => expect(granted()).toHaveLength(1))
    view.unmount()
    current = status({ state: 'waiting' }) // agent restarted and lost its token
    renderProvider()
    await waitFor(() => expect(granted()).toHaveLength(2))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument() // no second question
  })

  it('does nothing when no agent runs on this machine', async () => {
    current = null
    renderProvider()
    await waitFor(() => expect(agentApi.probeAgent).toHaveBeenCalled())
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByTestId('state')).toHaveTextContent('none')
  })

  it('does not ask an agent that is already running for this login', async () => {
    current = status({ state: 'ready' })
    renderProvider()
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('ready'))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('never asks or beats for anyone but Support', async () => {
    auth.user = { id: 'a1', role: 'admin' }
    renderProvider()
    await new Promise((r) => setTimeout(r, 50))
    expect(agentApi.probeAgent).not.toHaveBeenCalled()
    expect(api.apiFetch).not.toHaveBeenCalled()
  })

  it('tells the API the web is open (presence) while a Support is logged in', async () => {
    current = null
    renderProvider()
    await waitFor(() => expect(calls.some((c) => c.path === '/support-worker/presence' && c.init?.method === 'POST')).toBe(true))
  })

  it('Stop revokes the grant and disconnects the agent, and it stays off for this login', async () => {
    renderProvider()
    await userEvent.click(await screen.findByRole('button', { name: 'Có' }))
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('ready'))
    await userEvent.click(screen.getByRole('button', { name: 'stop' }))
    await waitFor(() => expect(calls.some((c) => c.path === '/support-worker/devices/dev1/revoke')).toBe(true))
    expect(agentApi.disconnectAgent).toHaveBeenCalled()
    await waitFor(() => expect(screen.getByTestId('consent')).toHaveTextContent('no'))
    expect(granted()).toHaveLength(1) // not granted again behind the user's back
  })

  it('tells the user when the agent cannot be reached after "Có"', async () => {
    agentApi.connectAgent.mockRejectedValue(new Error('refused'))
    renderProvider()
    await userEvent.click(await screen.findByRole('button', { name: 'Có' }))
    await waitFor(() => expect(toast.showToast).toHaveBeenCalledWith(expect.stringContaining('Không kết nối được'), 'error'))
  })

  it('disconnects the agent when the user logs out', async () => {
    current = status({ state: 'ready' })
    const view = renderProvider()
    await waitFor(() => expect(screen.getByTestId('state')).toHaveTextContent('ready'))
    auth.user = null
    view.rerender(
      <WorkerProvider ConsentDialog={ConsentDialog}>
        <Probe />
      </WorkerProvider>,
    )
    await waitFor(() => expect(agentApi.disconnectAgent).toHaveBeenCalled())
  })
})
