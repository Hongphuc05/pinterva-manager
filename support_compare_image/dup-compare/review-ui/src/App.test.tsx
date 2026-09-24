import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { ToastProvider } from './components/Toaster'
import type { Item, Job } from './types'

const job: Job = {
  id: 'j1', status: 'completed', requested_count: 3, processed_count: 3, duplicate_count: 2,
  error_count: 0, run_id: 'r1', created_at: '2026-09-24T10:03:38Z', finished_at: null,
}

const candidates = (n: number) =>
  [1, 2].map((r) => ({
    id: `i${n}-c${r}`, rank: r, order_code: `OLD-${n}${r}`, product_name: 'Áo cũ',
    image_url: `https://img.test/${n}${r}.png`, similarity: 0.9 - r / 100, phash_distance: 100,
    ssim: 0.4, color_delta_e: 3, classification: r === 1 ? 'TRUNG' : 'KHONG_TRUNG',
    sent_to_telegram: false, decision: 'pending',
  }))

const item = (n: number, review_status: Item['review_status'], selected: string | null = null): Item => ({
  id: `i${n}`, order_code: `DJ000${n}`, product_name: `Sản phẩm ${n}`, image_url: `https://img.test/n${n}.png`,
  model_says_duplicate: review_status !== 'no_match', review_status, selected_candidate_id: selected,
  reviewed_at: null, candidates: candidates(n),
})

let items: Item[]
let calls: { url: string; init?: RequestInit }[]

function renderApp() {
  return render(<ToastProvider><App /></ToastProvider>)
}

beforeEach(() => {
  calls = []
  items = [item(1, 'pending_review'), item(2, 'selected_duplicate', 'i2-c2'), item(3, 'no_match')]
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, init })
      const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => body })
      if (url === '/review/jobs') return ok({ jobs: [job] })
      if (url === '/review/jobs/j1') return ok({ job, items })
      if (init?.method === 'POST') return ok({})
      return Promise.reject(new Error(`unexpected ${url}`))
    }),
  )
})
afterEach(() => vi.unstubAllGlobals())

describe('review page', () => {
  it('shows the order code on the original and on every candidate image', async () => {
    renderApp()
    const card = await screen.findByTestId('order-DJ0001')
    expect(within(card).getAllByText('DJ0001').length).toBeGreaterThanOrEqual(2) // header + original figure
    expect(within(card).getByText('OLD-11')).toBeInTheDocument()
    expect(within(card).getByText('OLD-12')).toBeInTheDocument()
  })

  it('counts the three groups and switches tabs', async () => {
    renderApp()
    await screen.findByTestId('order-DJ0001')
    expect(screen.getByRole('tab', { name: /Cần duyệt/ })).toHaveTextContent('1')
    await userEvent.click(screen.getByRole('tab', { name: /Đã duyệt/ }))
    expect(screen.getByTestId('order-DJ0002')).toBeInTheDocument()
    expect(screen.queryByTestId('order-DJ0001')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: /Không thấy trùng/ }))
    expect(screen.getByTestId('order-DJ0003')).toBeInTheDocument()
  })

  it('selects a candidate and reloads the job', async () => {
    renderApp()
    const card = await screen.findByTestId('order-DJ0001')
    await userEvent.click(within(card).getAllByRole('button', { name: 'Chọn ảnh này là trùng' })[1])
    await waitFor(() =>
      expect(calls.some((c) => c.url === '/review/items/i1/select' && c.init?.body === JSON.stringify({ candidate_id: 'i1-c2' }))).toBe(true),
    )
    await waitFor(() => expect(calls.filter((c) => c.url === '/review/jobs/j1').length).toBe(2))
  })

  it('marks the model wrong', async () => {
    renderApp()
    const card = await screen.findByTestId('order-DJ0001')
    await userEvent.click(within(card).getByRole('button', { name: /Model sai/ }))
    await waitFor(() => expect(calls.some((c) => c.url === '/review/items/i1/reject' && c.init?.method === 'POST')).toBe(true))
  })

  it('freezes a pair that was already sent to Telegram', async () => {
    items = [{ ...item(2, 'selected_duplicate', 'i2-c2'), candidates: candidates(2).map((c) => ({ ...c, sent_to_telegram: c.id === 'i2-c2' })) }]
    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: /Đã duyệt/ }))
    const card = await screen.findByTestId('order-DJ0002')
    expect(within(card).getByText('Đã gửi Telegram')).toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: /Model sai/ })).not.toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: 'Chọn ảnh này là trùng' })).not.toBeInTheDocument()
  })

  it('shows an error state when the database cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, statusText: 'x', json: async () => ({ detail: 'Thiếu DATABASE_URL' }) })))
    renderApp()
    expect(await screen.findByText('Thiếu DATABASE_URL')).toBeInTheDocument()
    expect(screen.getByText('Mất kết nối DB')).toBeInTheDocument()
  })
})
