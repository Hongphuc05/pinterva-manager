import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  window.location.hash = ''
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
    await userEvent.click(within(card).getAllByRole('button', { name: 'Chọn trùng' })[1])
    await waitFor(() =>
      expect(calls.some((c) => c.url === '/review/items/i1/select' && c.init?.body === JSON.stringify({ candidate_id: 'i1-c2' }))).toBe(true),
    )
    await waitFor(() => expect(calls.filter((c) => c.url === '/review/jobs/j1').length).toBe(2))
  })

  it('picks a candidate with the number keys and marks the model wrong with X', async () => {
    renderApp()
    await screen.findByTestId('order-DJ0001')
    await userEvent.keyboard('2')
    await waitFor(() => expect(calls.some((c) => c.url === '/review/items/i1/select' && c.init?.body === JSON.stringify({ candidate_id: 'i1-c2' }))).toBe(true))
    await userEvent.keyboard('x')
    await waitFor(() => expect(calls.some((c) => c.url === '/review/items/i1/reject')).toBe(true))
  })

  it('loads images through the local proxy and falls back to a link when one cannot load', async () => {
    renderApp()
    const card = await screen.findByTestId('order-DJ0001')
    const img = within(card).getByAltText('OLD-11')
    expect(img).toHaveAttribute('src', '/review/img?url=' + encodeURIComponent('https://img.test/11.png'))
    fireEvent.error(img)
    expect(within(card).getByText('Không tải được ảnh')).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: 'Mở link gốc' })).toHaveAttribute('href', 'https://img.test/11.png')
  })

  it('opens a side-by-side detail modal, walks the top list with the arrows and closes with Esc', async () => {
    renderApp()
    const card = await screen.findByTestId('order-DJ0001')
    await userEvent.click(within(card).getByRole('button', { name: /Chi tiết/ }))

    const dialog = await screen.findByRole('dialog', { name: 'Chi tiết đơn DJ0001' })
    expect(within(dialog).getByText('Ảnh 1/2 trong top 2')).toBeInTheDocument()
    expect(within(dialog).getByAltText('DJ0001')).toBeInTheDocument() // original on the left
    expect(within(dialog).getByAltText('OLD-11')).toBeInTheDocument() // first candidate on the right

    await userEvent.keyboard('{ArrowRight}')
    expect(within(dialog).getByText('Ảnh 2/2 trong top 2')).toBeInTheDocument()
    expect(within(dialog).getByAltText('OLD-12')).toBeInTheDocument()
    await userEvent.keyboard('{ArrowLeft}')
    expect(within(dialog).getByAltText('OLD-11')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Ảnh sau' }))
    expect(within(dialog).getByAltText('OLD-12')).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Chi tiết đơn DJ0001' })).not.toBeInTheDocument()
  })

  it('selects the shown candidate from the detail modal', async () => {
    renderApp()
    await userEvent.click(within(await screen.findByTestId('order-DJ0001')).getByRole('button', { name: /Chi tiết/ }))
    await userEvent.keyboard('{ArrowRight}')
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Chọn ảnh này là trùng' }))
    await waitFor(() =>
      expect(calls.some((c) => c.url === '/review/items/i1/select' && c.init?.body === JSON.stringify({ candidate_id: 'i1-c2' }))).toBe(true),
    )
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
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
    expect(within(card).queryByRole('button', { name: 'Chọn trùng' })).not.toBeInTheDocument()
  })

  it('finds an uploaded picture in the pool and lists the matches with their codes and configuration', async () => {
    const result = {
      verdict: 'TRUNG', is_duplicate: true, pool_count: 85000, model_version: 'm', elapsed_ms: 1500,
      candidates: [{
        rank: 1, order_code: 'DJ777', product_name: 'Áo trùng', image_url: 'https://img.test/a.png',
        similarity: 0.97, phash_distance: 4, ssim: 0.9, color_delta_e: 1, classification: 'TRUNG', reasons: [],
        custom_config: { original: [{ key: 'Name', value: 'Ann' }, { key: 'extra_discount_ab', value: '0' }], translated_vn: [] },
      }],
    }
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => 'blob:mine', revokeObjectURL: () => {} }))
    const base = fetch as unknown as (u: string, i?: RequestInit) => Promise<unknown>
    vi.stubGlobal('fetch', vi.fn((url: string, init?: RequestInit) => {
      if (url.startsWith('/review/search')) {
        calls.push({ url, init })
        return Promise.resolve({ ok: true, status: 200, json: async () => result })
      }
      return base(url, init)
    }))
    renderApp()
    await userEvent.click(await screen.findByRole('tab', { name: 'Tìm ảnh' }))
    await userEvent.upload(screen.getByTestId('search-file'), new File(['x'], 'mine.png', { type: 'image/png' }))
    expect(await screen.findByText('DJ777')).toBeInTheDocument()
    expect(screen.getByText('Model: có ảnh trùng')).toBeInTheDocument()
    expect(screen.getByText(/Name/)).toBeInTheDocument()
    expect(screen.queryByText(/extra_discount/)).not.toBeInTheDocument()
    expect(calls.some((c) => c.url.startsWith('/review/search') && c.init?.method === 'POST')).toBe(true)
  })

  it('shows an error state when the database cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve({ ok: false, statusText: 'x', json: async () => ({ detail: 'Thiếu DATABASE_URL' }) })))
    renderApp()
    expect(await screen.findByText('Thiếu DATABASE_URL')).toBeInTheDocument()
    expect(screen.getByText('Mất kết nối')).toBeInTheDocument()
  })
})
