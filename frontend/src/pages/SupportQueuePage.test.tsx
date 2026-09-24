import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ToastProvider } from '../context/ToastContext'
import type { QueueState } from '../features/dupReview/types'
import { SupportQueuePage } from './SupportQueuePage'

vi.mock('../components/DashboardLayout', () => ({ DashboardLayout: ({ children }: { children: React.ReactNode }) => <>{children}</> }))

const auth = vi.hoisted(() => ({ role: 'support' }))
vi.mock('../auth/AuthContext', () => ({
  useAuth: () => ({ user: { id: 'u1', username: 'sup', full_name: 'Support A', role: auth.role } }),
}))

const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), apiFetch: api.apiFetch }))

const now = new Date().toISOString()
const emptyQueue: QueueState = { workers: { ready: 0, paused: 0, offline: 0, devices: [] }, running: [], queued: [], searches: [], recent: [] }
const job = (over: object) => ({
  id: 'abcdef123456', status: 'queued', requested_count: 12, processed_count: 0, duplicate_count: 0, error_count: 0,
  requested_by: 'Support A', worker_name: null, created_at: now, started_at: null, heartbeat_at: null, finished_at: null, last_error: null,
  ...over,
})

let queue: QueueState
let calls: { path: string; init?: RequestInit }[]

const renderPage = (entry = '/support-queue') =>
  render(<MemoryRouter initialEntries={[entry]}><ToastProvider><SupportQueuePage /></ToastProvider></MemoryRouter>)

beforeEach(() => {
  auth.role = 'support'
  queue = emptyQueue
  calls = []
  vi.spyOn(window, 'confirm').mockReturnValue(true)
  api.apiFetch.mockReset().mockImplementation((path: string, init?: RequestInit) => {
    calls.push({ path, init })
    if (path === '/support-review/queue') return Promise.resolve(queue)
    if (path === '/support-worker/devices/lookup') return Promise.resolve({ machine_name: 'MacBook Phúc', user_code: 'ABCD-2345' })
    return Promise.resolve({})
  })
})
afterEach(() => vi.restoreAllMocks())

describe('support queue page', () => {
  it('warns when work is waiting but no machine is ready', async () => {
    queue = { ...emptyQueue, queued: [job({ position: 1 })] }
    renderPage()
    expect(await screen.findByText(/chưa có máy Support nào sẵn sàng/)).toBeInTheDocument()
    expect(screen.getByText('Job abcdef12')).toBeInTheDocument()
    expect(screen.getByText('#1')).toBeInTheDocument()
    expect(screen.getByText(/12 đơn/)).toBeInTheDocument()
  })

  it('shows a running job with its progress, the machine and the machines list', async () => {
    queue = {
      workers: { ready: 1, paused: 0, offline: 0, devices: [{ id: 'd1', machine_name: 'MacBook Phúc', state: 'busy', user_name: 'Support A', busy_with: 'job:x', last_seen_at: now, presence_at: now }] },
      running: [job({ status: 'running', processed_count: 6, duplicate_count: 2, worker_name: 'MacBook Phúc', heartbeat_at: now })],
      queued: [], searches: [], recent: [],
    }
    renderPage()
    expect(await screen.findByRole('progressbar')).toHaveAttribute('aria-valuenow', '50')
    expect(screen.getByText('6/12 đơn đã so')).toBeInTheDocument()
    expect(screen.getByText('máy: MacBook Phúc')).toBeInTheDocument()
    expect(screen.getByText('Đang chạy', { selector: 'span' })).toBeInTheDocument()
    expect(screen.queryByText(/chưa có máy Support nào sẵn sàng/)).not.toBeInTheDocument()
  })

  it('lets the user allow a machine by its code and then reloads the queue', async () => {
    renderPage('/support-queue?code=ABCD-2345')
    expect(await screen.findByText('MacBook Phúc')).toBeInTheDocument()
    expect(screen.getByText(/đăng xuất hoặc đóng web thì máy tự dừng/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Cho phép' }))
    await waitFor(() =>
      expect(calls.some((c) => c.path === '/support-worker/devices/approve' && c.init?.body === JSON.stringify({ user_code: 'ABCD-2345' }))).toBe(true),
    )
  })

  it('looks the code up when it is typed instead of opened from the agent link', async () => {
    renderPage()
    await userEvent.type(await screen.findByLabelText(/Kết nối máy Support/), 'abcd2345')
    await userEvent.click(screen.getByRole('button', { name: 'Kiểm tra mã' }))
    expect(await screen.findByText('MacBook Phúc')).toBeInTheDocument()
    expect(calls.find((c) => c.path === '/support-worker/devices/lookup')?.init?.body).toBe(JSON.stringify({ user_code: 'ABCD2345' }))
  })

  it('only an admin can cancel a queued job', async () => {
    queue = { ...emptyQueue, queued: [job({ position: 1 })] }
    const support = renderPage()
    await screen.findByText('Job abcdef12')
    expect(screen.queryByRole('button', { name: /Hủy/ })).not.toBeInTheDocument()
    support.unmount()

    auth.role = 'admin'
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: /Hủy/ }))
    await waitFor(() => expect(calls.some((c) => c.path === '/support-review/jobs/abcdef123456/cancel' && c.init?.method === 'POST')).toBe(true))
  })

  it('lists image searches with their state and recent jobs with a link to review them', async () => {
    queue = {
      ...emptyQueue,
      searches: [{ id: 's1', filename: 'cat.png', status: 'queued', requested_by: 'Support A', created_at: now, finished_at: null, last_error: null }],
      recent: [job({ status: 'completed', processed_count: 12, duplicate_count: 3, finished_at: now })],
    }
    renderPage()
    const search = (await screen.findByText('cat.png')).closest('li') as HTMLElement
    expect(within(search).getByText('đang chờ')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Job abcdef12' })).toHaveAttribute('href', '/duplicate-review?job=abcdef123456')
  })
})
