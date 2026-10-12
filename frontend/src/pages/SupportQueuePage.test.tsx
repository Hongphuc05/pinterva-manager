import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AgentStatus } from '../features/worker/agentClient'
import type { QueueOverview } from '../features/worker/queueApi'
import { SupportQueuePage } from './SupportQueuePage'

vi.mock('../components/DashboardLayout', () => ({ DashboardLayout: ({ children }: { children: React.ReactNode }) => <>{children}</> }))

const worker = vi.hoisted(() => ({ value: {} as Record<string, unknown> }))
vi.mock('../features/worker/WorkerProvider', () => ({ useWorker: () => worker.value }))

const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), apiFetch: api.apiFetch }))

const now = new Date().toISOString()
const job = (over: object) => ({
  id: 'abcdef123456', status: 'queued', requested_count: 12, remaining_count: 12, requested_by: 'Support A',
  created_at: now, started_at: null, worker_name: null, ...over,
})
const agent = (over: Partial<AgentStatus> = {}): AgentStatus => ({ agent: 'support-compare', version: 1, name: 'MacBook Phúc', state: 'ready', device: 'mps', available_devices: ['cpu', 'mps'], model_loaded: true, ...over })

let queue: QueueOverview
let orders: { orders: { order_id: string; external_order_id: string; product_name: string | null; thumbnail_url: string | null }[] }
let calls: string[]
const allow = vi.fn()
const stop = vi.fn()
const switchDevice = vi.fn()

function setWorker(over: Record<string, unknown>) {
  worker.value = { agent: null, probed: true, consent: null, busy: false, allow, decline: vi.fn(), stop, switchDevice, ...over }
}

beforeEach(() => {
  queue = { waiting_jobs: 0, jobs: [], machines: { ready: 0, paused: 0, offline: 0 } }
  orders = { orders: [] }
  calls = []
  allow.mockReset()
  stop.mockReset()
  switchDevice.mockReset()
  setWorker({})
  api.apiFetch.mockReset().mockImplementation((path: string) => {
    calls.push(path)
    if (path === '/support-worker/queue') return Promise.resolve(queue)
    if (path.startsWith('/support-worker/queue/jobs/')) return Promise.resolve({ id: 'abcdef123456', status: 'queued', requested_count: 12, ...orders })
    return Promise.resolve({})
  })
})
afterEach(() => vi.restoreAllMocks())

describe('support queue page', () => {
  it('shows how many jobs are waiting and lists them oldest first', async () => {
    queue = {
      waiting_jobs: 2,
      jobs: [job({}), job({ id: 'ffff00001111', status: 'running', remaining_count: 3, requested_count: 5, worker_name: 'MacBook Phúc' })],
      machines: { ready: 1, paused: 0, offline: 0 },
    }
    render(<SupportQueuePage />)
    await waitFor(() => expect(screen.getByTestId('waiting-jobs')).toHaveTextContent('2'))
    const rows = screen.getAllByRole('listitem').filter((li) => within(li).queryByRole('button', { expanded: false }))
    expect(within(rows[0]).getByText('12 đơn chờ kiểm tra')).toBeInTheDocument()
    expect(within(rows[0]).getByText('Đang chờ')).toBeInTheDocument()
    expect(within(rows[1]).getByText('3 đơn chờ kiểm tra')).toBeInTheDocument()
    expect(within(rows[1]).getByText('Đang chạy')).toBeInTheDocument()
    expect(within(rows[1]).getByText(/máy MacBook Phúc/)).toBeInTheDocument()
  })

  it("shows the team's hosting machine to an account that runs no agent itself", async () => {
    setWorker({ agent: null, probed: true })
    queue = {
      waiting_jobs: 0,
      jobs: [],
      machines: { ready: 1, paused: 0, offline: 0 },
      hosts: [
        {
          id: 'h1', machine_name: 'MacBook-Phuc', owner: 'Support W', state: 'busy', device: 'cpu',
          progress: { phase: 'syncing_pool', pool_loaded: 44000, pool_total: 88000 },
          last_seen_at: now, expires_at: now,
        },
      ],
    }
    render(<SupportQueuePage />)
    const hosts = await screen.findByTestId('agent-hosts')
    expect(within(hosts).getByText('MacBook-Phuc')).toBeInTheDocument()
    expect(within(hosts).getByText('Đang chạy job')).toBeInTheDocument()
    expect(within(hosts).getByText(/Tài khoản Support W · CPU/)).toBeInTheDocument()
    expect(within(hosts).getByText(/44\.000 \/ 88\.000 \(50%\)/)).toBeInTheDocument()
    expect(screen.getByText('Không cần chạy agent trên máy này')).toBeInTheDocument()
    expect(screen.queryByText('Máy này chưa chạy agent')).not.toBeInTheDocument()
  })

  it('says when a hosting machine stopped answering', async () => {
    queue = {
      waiting_jobs: 0, jobs: [], machines: { ready: 0, paused: 0, offline: 1 },
      hosts: [{ id: 'h1', machine_name: 'MacBook-Phuc', owner: 'Support W', state: 'offline', device: null, progress: {}, last_seen_at: now, expires_at: now }],
    }
    render(<SupportQueuePage />)
    expect(await screen.findByText(/Agent không phản hồi/)).toBeInTheDocument()
    expect(screen.getByText('Mất kết nối')).toBeInTheDocument()
  })

  it('says so when nothing is waiting', async () => {
    render(<SupportQueuePage />)
    expect(await screen.findByText('Không có job nào đang đợi.')).toBeInTheDocument()
    expect(screen.getByTestId('waiting-jobs')).toHaveTextContent('0')
  })

  it('opens a job to show the orders still waiting for the duplicate check', async () => {
    queue = { waiting_jobs: 1, jobs: [job({})], machines: { ready: 0, paused: 0, offline: 0 } }
    orders = {
      orders: [
        { order_id: 'o1', external_order_id: 'DJ4048136', product_name: 'Áo Bố', thumbnail_url: 'https://cdn.test/a.png' },
        { order_id: 'o2', external_order_id: 'DJ4048184', product_name: null, thumbnail_url: null },
      ],
    }
    render(<SupportQueuePage />)
    await userEvent.click(await screen.findByRole('button', { name: /12 đơn chờ kiểm tra/ }))
    expect(await screen.findByText('DJ4048136')).toBeInTheDocument()
    expect(screen.getByText('DJ4048184')).toBeInTheDocument()
    expect(screen.getByText('Áo Bố')).toBeInTheDocument()
    expect(calls).toContain('/support-worker/queue/jobs/abcdef123456/orders')
  })

  it('tells a job with nothing left to check', async () => {
    queue = { waiting_jobs: 1, jobs: [job({ remaining_count: 0 })], machines: { ready: 0, paused: 0, offline: 0 } }
    render(<SupportQueuePage />)
    await userEvent.click(await screen.findByRole('button', { name: /0 đơn chờ kiểm tra/ }))
    expect(await screen.findByText('Không còn đơn nào chờ kiểm tra trong job này.')).toBeInTheDocument()
  })

  it('offers to allow this machine when the agent is here but was not allowed yet', async () => {
    setWorker({ agent: agent({ state: 'waiting' }), consent: 'no' })
    render(<SupportQueuePage />)
    expect(await screen.findByText('Bạn đã từ chối cho máy này chạy hàng đợi')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cho phép máy này' }))
    expect(allow).toHaveBeenCalled()
  })

  it('shows this machine running the queue and lets Support stop it', async () => {
    setWorker({ agent: agent({ state: 'busy' }), consent: 'yes' })
    render(<SupportQueuePage />)
    expect(await screen.findByText('Máy này đang chạy hàng đợi')).toBeInTheDocument()
    expect(screen.getByText(/MacBook Phúc · MPS/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Dừng máy này' }))
    expect(stop).toHaveBeenCalled()
  })

  it('lets Support switch device, greys out ones unavailable on this machine', async () => {
    setWorker({ agent: agent({ state: 'ready', device: 'cpu', available_devices: ['cpu'] }), consent: 'yes' })
    render(<SupportQueuePage />)
    await screen.findByText('Máy này sẵn sàng chạy hàng đợi')

    const cpuButton = screen.getByRole('button', { name: 'CPU' })
    const gpuButton = screen.getByRole('button', { name: 'GPU (Apple)' })
    expect(cpuButton).toBeDisabled() // already active
    expect(gpuButton).toBeDisabled() // not in available_devices on this run

    await userEvent.click(gpuButton)
    expect(switchDevice).not.toHaveBeenCalled()
  })

  it('switching device calls switchDevice and reports success', async () => {
    switchDevice.mockResolvedValue(undefined)
    setWorker({ agent: agent({ state: 'ready', device: 'cpu', available_devices: ['cpu', 'mps'] }), consent: 'yes' })
    render(<SupportQueuePage />)
    await screen.findByText('Máy này sẵn sàng chạy hàng đợi')

    await userEvent.click(screen.getByRole('button', { name: 'GPU (Apple)' }))
    expect(switchDevice).toHaveBeenCalledWith('mps')
  })

  it('a failed switch shows the agent\'s own reason', async () => {
    switchDevice.mockRejectedValue(new Error('Máy đang xử lý job, chờ xong rồi đổi.'))
    setWorker({ agent: agent({ state: 'busy', device: 'cpu', available_devices: ['cpu', 'mps'] }), consent: 'yes' })
    render(<SupportQueuePage />)
    await screen.findByText('Máy này đang chạy hàng đợi')

    await userEvent.click(screen.getByRole('button', { name: 'GPU (Apple)' }))
    expect(switchDevice).toHaveBeenCalledWith('mps')
  })

  it('explains how to start the agent when none answers on this machine', async () => {
    setWorker({ agent: null, probed: true })
    render(<SupportQueuePage />)
    expect(await screen.findByText('Máy này chưa chạy agent')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cho phép/ })).not.toBeInTheDocument()
  })

  it('keeps working when the queue cannot be loaded', async () => {
    api.apiFetch.mockRejectedValue(new Error('offline'))
    render(<SupportQueuePage />)
    expect(await screen.findByText(/Không tải được hàng đợi/)).toBeInTheDocument()
  })
})
