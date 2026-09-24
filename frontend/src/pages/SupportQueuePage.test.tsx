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
const agent = (over: Partial<AgentStatus> = {}): AgentStatus => ({ agent: 'support-compare', version: 1, name: 'MacBook Phúc', state: 'ready', device: 'mps', model_loaded: true, ...over })

let queue: QueueOverview
let orders: { orders: { order_id: string; external_order_id: string; product_name: string | null; thumbnail_url: string | null }[] }
let calls: string[]
const allow = vi.fn()
const stop = vi.fn()

function setWorker(over: Record<string, unknown>) {
  worker.value = { agent: null, probed: true, consent: null, busy: false, allow, decline: vi.fn(), stop, ...over }
}

beforeEach(() => {
  queue = { waiting_jobs: 0, jobs: [], machines: { ready: 0, paused: 0, offline: 0 } }
  orders = { orders: [] }
  calls = []
  allow.mockReset()
  stop.mockReset()
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
