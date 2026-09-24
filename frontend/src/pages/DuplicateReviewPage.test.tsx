import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LOCKED_EVENT, getReviewToken, setReviewToken } from '../features/dupReview/access'
import { ApiError } from '../api/client'
import { ToastProvider } from '../context/ToastContext'
import type { Item, Job } from '../features/dupReview/types'
import { clearProxiedCache } from '../features/dupReview/components/ProxiedImg'
import { DuplicateReviewPage } from './DuplicateReviewPage'

const mocks = vi.hoisted(() => ({ apiFetch: vi.fn(), apiFetchBlob: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  apiFetch: mocks.apiFetch,
  apiFetchBlob: mocks.apiFetchBlob,
}))

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
let calls: { path: string; init?: RequestInit }[]
let searchN: number

const searchResult = (code: string) => ({
  verdict: 'TRUNG', is_duplicate: true, pool_count: 85000, model_version: 'm', elapsed_ms: 900,
  candidates: [{
    rank: 1, order_code: code, product_name: 'Áo trùng', image_url: `https://img.test/${code}.png`,
    similarity: 0.97, phash_distance: 4, ssim: 0.9, color_delta_e: 1, classification: 'TRUNG', reasons: [],
    custom_config: { original: [{ key: 'Name', value: 'Ann' }, { key: 'extra_discount_ab', value: '0' }], translated_vn: [] },
  }],
})

let access: { has_password: boolean; unlocked: boolean }

function renderPage(entry = '/duplicate-review') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <ToastProvider><DuplicateReviewPage /></ToastProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  clearProxiedCache()
  localStorage.clear()
  sessionStorage.clear()
  setReviewToken('tok')
  access = { has_password: true, unlocked: true }
  calls = []
  searchN = 0
  items = [item(1, 'pending_review'), item(2, 'selected_duplicate', 'i2-c2'), item(3, 'no_match')]
  let blobs = 0
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: () => `blob:img-${++blobs}`, revokeObjectURL: () => {} }))
  mocks.apiFetchBlob.mockReset().mockResolvedValue(new Blob(['x']))
  mocks.apiFetch.mockReset().mockImplementation((path: string, init?: RequestInit) => {
    calls.push({ path, init })
    if (path === '/support-review/access') return Promise.resolve(access)
    if (path.startsWith('/support-review/jobs?')) return Promise.resolve({ jobs: [job] })
    if (path === '/support-review/jobs/j1') return Promise.resolve({ job, items })
    if (path.startsWith('/support-review/search?')) return Promise.resolve({ id: `s${++searchN}` })
    if (path.startsWith('/support-review/search/s')) {
      return Promise.resolve({ id: path.split('/').pop(), status: 'completed', error: null, result: searchResult(`DJ-S${searchN}`) })
    }
    if (init?.method === 'POST') return Promise.resolve({})
    return Promise.reject(new Error(`unexpected ${path}`))
  })
})
afterEach(() => vi.unstubAllGlobals())

const posted = (path: string, body?: unknown) =>
  calls.some((c) => c.path === path && c.init?.method === 'POST' && (body === undefined || c.init?.body === JSON.stringify(body)))

describe('duplicate review page', () => {
  it('shows the order code on the original and on every candidate image', async () => {
    renderPage()
    const card = await screen.findByTestId('order-DJ0001')
    expect(within(card).getAllByText('DJ0001').length).toBeGreaterThanOrEqual(2)
    expect(within(card).getByText('OLD-11')).toBeInTheDocument()
    expect(within(card).getByText('OLD-12')).toBeInTheDocument()
  })

  it('counts the three groups and switches tabs', async () => {
    renderPage()
    await screen.findByTestId('order-DJ0001')
    expect(screen.getByRole('tab', { name: /Cần duyệt/ })).toHaveTextContent('1')
    await userEvent.click(screen.getByRole('tab', { name: /Đã duyệt/ }))
    expect(screen.getByTestId('order-DJ0002')).toBeInTheDocument()
    expect(screen.queryByTestId('order-DJ0001')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: /Không thấy trùng/ }))
    expect(screen.getByTestId('order-DJ0003')).toBeInTheDocument()
  })

  it('selects a candidate and reloads the job', async () => {
    renderPage()
    const card = await screen.findByTestId('order-DJ0001')
    await userEvent.click(within(card).getAllByRole('button', { name: 'Chọn trùng' })[1])
    await waitFor(() => expect(posted('/support-review/items/i1/select', { candidate_id: 'i1-c2' })).toBe(true))
    await waitFor(() => expect(calls.filter((c) => c.path === '/support-review/jobs/j1').length).toBe(2))
  })

  it('picks a candidate with the number keys and marks the model wrong with X', async () => {
    renderPage()
    await screen.findByTestId('order-DJ0001')
    await userEvent.keyboard('2')
    await waitFor(() => expect(posted('/support-review/items/i1/select', { candidate_id: 'i1-c2' })).toBe(true))
    await userEvent.keyboard('x')
    await waitFor(() => expect(posted('/support-review/items/i1/reject')).toBe(true))
  })

  it('loads images through the authenticated proxy and falls back to a link when one cannot load', async () => {
    mocks.apiFetchBlob.mockImplementation((path: string) =>
      path.includes(encodeURIComponent('https://img.test/11.png')) ? Promise.reject(new ApiError(502, 'x')) : Promise.resolve(new Blob(['x'])),
    )
    renderPage()
    const card = await screen.findByTestId('order-DJ0001')
    await waitFor(() => expect(within(card).getByText('Không tải được ảnh')).toBeInTheDocument())
    expect(within(card).getByRole('link', { name: 'Mở link gốc' })).toHaveAttribute('href', 'https://img.test/11.png')
    expect(within(card).getByAltText('OLD-12')).toHaveAttribute('src', expect.stringMatching(/^blob:img-/))
    expect(mocks.apiFetchBlob).toHaveBeenCalledWith('/support-review/img?url=' + encodeURIComponent('https://img.test/12.png'), { 'X-Review-Token': 'tok' })
  })

  it('opens a side-by-side detail modal, walks the top list with the arrows and closes with Esc', async () => {
    renderPage()
    const card = await screen.findByTestId('order-DJ0001')
    await userEvent.click(within(card).getByRole('button', { name: /Chi tiết/ }))

    const dialog = await screen.findByRole('dialog', { name: 'Chi tiết đơn DJ0001' })
    expect(within(dialog).getByText('Ảnh 1/2 trong top 2')).toBeInTheDocument()
    expect(await within(dialog).findByAltText('DJ0001')).toBeInTheDocument()
    expect(await within(dialog).findByAltText('OLD-11')).toBeInTheDocument()

    await userEvent.keyboard('{ArrowRight}')
    expect(within(dialog).getByText('Ảnh 2/2 trong top 2')).toBeInTheDocument()
    expect(await within(dialog).findByAltText('OLD-12')).toBeInTheDocument()
    await userEvent.keyboard('{ArrowLeft}')
    expect(await within(dialog).findByAltText('OLD-11')).toBeInTheDocument()

    await userEvent.keyboard('{Escape}')
    expect(screen.queryByRole('dialog', { name: 'Chi tiết đơn DJ0001' })).not.toBeInTheDocument()
  })

  it('selects the shown candidate from the detail modal', async () => {
    renderPage()
    await userEvent.click(within(await screen.findByTestId('order-DJ0001')).getByRole('button', { name: /Chi tiết/ }))
    await userEvent.keyboard('{ArrowRight}')
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Chọn ảnh này là trùng' }))
    await waitFor(() => expect(posted('/support-review/items/i1/select', { candidate_id: 'i1-c2' })).toBe(true))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('marks the model wrong', async () => {
    renderPage()
    const card = await screen.findByTestId('order-DJ0001')
    await userEvent.click(within(card).getByRole('button', { name: /Model sai/ }))
    await waitFor(() => expect(posted('/support-review/items/i1/reject')).toBe(true))
  })

  it('freezes a pair that was already sent to Telegram', async () => {
    items = [{ ...item(2, 'selected_duplicate', 'i2-c2'), candidates: candidates(2).map((c) => ({ ...c, sent_to_telegram: c.id === 'i2-c2' })) }]
    renderPage()
    await userEvent.click(await screen.findByRole('tab', { name: /Đã duyệt/ }))
    const card = await screen.findByTestId('order-DJ0002')
    expect(within(card).getByText('Đã gửi Telegram')).toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: /Model sai/ })).not.toBeInTheDocument()
    expect(within(card).queryByRole('button', { name: 'Chọn trùng' })).not.toBeInTheDocument()
  })

  it('queues an uploaded picture for a Support machine, then lists the matches with codes and configuration', async () => {
    renderPage()
    await userEvent.click(await screen.findByRole('tab', { name: 'Tìm ảnh' }))
    await userEvent.upload(screen.getByTestId('search-file'), new File(['x'], 'mine.png', { type: 'image/png' }))
    expect(await screen.findByText('DJ-S1')).toBeInTheDocument()
    expect(screen.getByText('Model: có ảnh trùng')).toBeInTheDocument()
    expect(screen.getByText(/Name/)).toBeInTheDocument()
    expect(screen.queryByText(/extra_discount/)).not.toBeInTheDocument()
    expect(calls.some((c) => c.path === '/support-review/search?top_k=10' && c.init?.body instanceof FormData)).toBe(true)
  })

  it('says so while no machine has picked the search up yet', async () => {
    mocks.apiFetch.mockImplementation((path: string) => {
      if (path === '/support-review/access') return Promise.resolve(access)
      if (path.startsWith('/support-review/jobs?')) return Promise.resolve({ jobs: [] })
      if (path.startsWith('/support-review/search?')) return Promise.resolve({ id: 's1' })
      return Promise.resolve({ id: 's1', status: 'queued', result: null, error: null })
    })
    renderPage('/duplicate-review?tab=search')
    await userEvent.upload(await screen.findByTestId('search-file'), new File(['x'], 'wait.png', { type: 'image/png' }))
    expect(await screen.findByText(/Đang chờ một máy Support nhận việc/)).toBeInTheDocument()
  })

  it('shows the machine error when a search fails', async () => {
    mocks.apiFetch.mockImplementation((path: string) => {
      if (path === '/support-review/access') return Promise.resolve(access)
      if (path.startsWith('/support-review/jobs?')) return Promise.resolve({ jobs: [] })
      if (path.startsWith('/support-review/search?')) return Promise.resolve({ id: 's1' })
      return Promise.resolve({ id: 's1', status: 'failed', result: null, error: 'Pool chưa có embedding' })
    })
    renderPage('/duplicate-review?tab=search')
    await userEvent.upload(await screen.findByTestId('search-file'), new File(['x'], 'bad.png', { type: 'image/png' }))
    expect(await screen.findByText('Pool chưa có embedding')).toBeInTheDocument()
  })

  it('keeps searches when switching tabs, lets you reopen or delete them, and restores them after a reload', async () => {
    const view = renderPage()
    await userEvent.click(await screen.findByRole('tab', { name: 'Tìm ảnh' }))
    await userEvent.upload(screen.getByTestId('search-file'), new File(['x'], 'first.png', { type: 'image/png' }))
    expect(await screen.findByText('DJ-S1')).toBeInTheDocument()
    await userEvent.upload(screen.getByTestId('search-file'), new File(['x'], 'second.png', { type: 'image/png' }))
    expect(await screen.findByText('DJ-S2')).toBeInTheDocument()
    expect(screen.getByText('Lịch sử (2)')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('tab', { name: 'Duyệt kết quả' }))
    await userEvent.click(screen.getByRole('tab', { name: 'Tìm ảnh' }))
    expect(screen.getByText('Lịch sử (2)')).toBeInTheDocument()
    expect(screen.getByText('DJ-S2')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /^first\.png/ }))
    expect(screen.getByText('DJ-S1')).toBeInTheDocument()
    expect(screen.queryByText('DJ-S2')).not.toBeInTheDocument()

    view.unmount()
    renderPage('/duplicate-review?tab=search')
    expect(await screen.findByText('Lịch sử (2)')).toBeInTheDocument()
    expect(screen.getByText('DJ-S2')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Xóa second.png' }))
    expect(screen.getByText('Lịch sử (1)')).toBeInTheDocument()
    expect(screen.getByText('DJ-S1')).toBeInTheDocument()
  })

  it('opens the job named in the link', async () => {
    renderPage('/duplicate-review?job=j1')
    await screen.findByTestId('order-DJ0001')
    expect(calls.some((c) => c.path === '/support-review/jobs/j1')).toBe(true)
  })

  it('shows an error state when the jobs cannot be loaded', async () => {
    mocks.apiFetch.mockImplementation((path: string) =>
      path === '/support-review/access' ? Promise.resolve(access) : Promise.reject(new ApiError(500, 'Máy chủ lỗi')),
    )
    renderPage()
    expect(await screen.findByText('Máy chủ lỗi')).toBeInTheDocument()
  })

  it('lists the jobs on the left and switches job with a click', async () => {
    const older = { ...job, id: 'j0', created_at: '2026-09-23T08:00:00Z', processed_count: 1, requested_count: 1, duplicate_count: 0 }
    mocks.apiFetch.mockImplementation((path: string, init?: RequestInit) => {
      calls.push({ path, init })
      if (path === '/support-review/access') return Promise.resolve(access)
      if (path.startsWith('/support-review/jobs?')) return Promise.resolve({ jobs: [job, older] })
      if (path === '/support-review/jobs/j1') return Promise.resolve({ job, items })
      if (path === '/support-review/jobs/j0') return Promise.resolve({ job: older, items: [] })
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    renderPage()
    await screen.findByTestId('order-DJ0001')
    const rail = screen.getByRole('complementary', { name: 'Danh sách job' })
    expect(within(rail).getAllByRole('button', { name: /đơn/ })).toHaveLength(2)
    await userEvent.click(within(rail).getAllByRole('button', { name: /đơn/ })[1])
    await waitFor(() => expect(calls.some((c) => c.path === '/support-review/jobs/j0')).toBe(true))
    expect(await screen.findByText('Không có đơn nào trong mục này')).toBeInTheDocument()
  })
})

describe('hidden area password', () => {
  it('asks for the password first and opens the console with it', async () => {
    setReviewToken(null)
    access = { has_password: true, unlocked: false }
    mocks.apiFetch.mockImplementation((path: string, init?: RequestInit) => {
      calls.push({ path, init })
      if (path === '/support-review/access') return Promise.resolve(access)
      if (path === '/support-review/access/unlock') return Promise.resolve({ token: 'fresh' })
      if (path.startsWith('/support-review/jobs?')) return Promise.resolve({ jobs: [job] })
      if (path === '/support-review/jobs/j1') return Promise.resolve({ job, items })
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    renderPage()
    await userEvent.type(await screen.findByLabelText('Mật khẩu'), 'secret1')
    await userEvent.click(screen.getByRole('button', { name: 'Mở' }))
    expect(await screen.findByTestId('order-DJ0001')).toBeInTheDocument()
    expect(getReviewToken()).toBe('fresh')
    expect(calls.find((c) => c.path === '/support-review/access/unlock')?.init?.body).toBe(JSON.stringify({ password: 'secret1' }))
    expect(screen.queryByText('Nhập mật khẩu để mở')).not.toBeInTheDocument()
  })

  it('shows the server message on a wrong password and stays locked', async () => {
    setReviewToken(null)
    access = { has_password: true, unlocked: false }
    mocks.apiFetch.mockImplementation((path: string) =>
      path === '/support-review/access' ? Promise.resolve(access) : Promise.reject(new ApiError(403, 'Mật khẩu không đúng.')),
    )
    renderPage()
    await userEvent.type(await screen.findByLabelText('Mật khẩu'), 'nope')
    await userEvent.click(screen.getByRole('button', { name: 'Mở' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Mật khẩu không đúng.')
    expect(getReviewToken()).toBeNull()
  })

  it('the first visit chooses the password (twice) before entering', async () => {
    setReviewToken(null)
    access = { has_password: false, unlocked: false }
    mocks.apiFetch.mockImplementation((path: string, init?: RequestInit) => {
      calls.push({ path, init })
      if (path === '/support-review/access') return Promise.resolve(access)
      if (path === '/support-review/access/setup') return Promise.resolve({ token: 'first' })
      if (path.startsWith('/support-review/jobs?')) return Promise.resolve({ jobs: [] })
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    renderPage()
    await userEvent.type(await screen.findByLabelText('Mật khẩu mới'), 'secret1')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu'), 'different')
    await userEvent.click(screen.getByRole('button', { name: 'Đặt mật khẩu và vào' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('chưa giống nhau')
    expect(calls.some((c) => c.path === '/support-review/access/setup')).toBe(false)

    await userEvent.clear(screen.getByLabelText('Nhập lại mật khẩu'))
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu'), 'secret1')
    await userEvent.click(screen.getByRole('button', { name: 'Đặt mật khẩu và vào' }))
    expect(await screen.findByText('Chưa có job nào')).toBeInTheDocument()
    expect(getReviewToken()).toBe('first')
  })

  it('locks again from the header button and when the API says the session is locked', async () => {
    renderPage()
    await screen.findByTestId('order-DJ0001')
    await userEvent.click(screen.getByRole('button', { name: /^Khóa$/ }))
    expect(await screen.findByText('Nhập mật khẩu để mở')).toBeInTheDocument()
    expect(getReviewToken()).toBeNull()
  })

  it('goes back to the password screen when a request is refused as locked', async () => {
    renderPage()
    await screen.findByTestId('order-DJ0001')
    window.dispatchEvent(new Event(LOCKED_EVENT))
    expect(await screen.findByText('Nhập mật khẩu để mở')).toBeInTheDocument()
  })

  it('changes the password from Cài đặt and keeps the new token', async () => {
    mocks.apiFetch.mockImplementation((path: string, init?: RequestInit) => {
      calls.push({ path, init })
      if (path === '/support-review/access') return Promise.resolve(access)
      if (path === '/support-review/access/change') return Promise.resolve({ token: 'renewed' })
      if (path.startsWith('/support-review/jobs?')) return Promise.resolve({ jobs: [] })
      return Promise.reject(new Error(`unexpected ${path}`))
    })
    renderPage('/duplicate-review?tab=settings')
    await userEvent.type(await screen.findByLabelText('Mật khẩu hiện tại'), 'secret1')
    await userEvent.type(screen.getByLabelText('Mật khẩu mới'), 'newpass2')
    await userEvent.type(screen.getByLabelText('Nhập lại mật khẩu mới'), 'newpass2')
    await userEvent.click(screen.getByRole('button', { name: 'Đổi mật khẩu' }))
    await waitFor(() => expect(getReviewToken()).toBe('renewed'))
    expect(calls.find((c) => c.path === '/support-review/access/change')?.init?.body).toBe(
      JSON.stringify({ current_password: 'secret1', new_password: 'newpass2' }),
    )
  })

  it('sends the review token with every review request', async () => {
    renderPage()
    await screen.findByTestId('order-DJ0001')
    const withHeaders = mocks.apiFetch.mock.calls.filter(([path]) => String(path).startsWith('/support-review/jobs'))
    expect(withHeaders.length).toBeGreaterThan(0)
    for (const [, init] of withHeaders) expect((init as RequestInit).headers).toMatchObject({ 'X-Review-Token': 'tok' })
  })

  it('lists every job in the history tab and opens one for review', async () => {
    renderPage('/duplicate-review?tab=jobs')
    const row = (await screen.findByText('3/3')).closest('tr') as HTMLElement
    await userEvent.click(within(row).getByRole('button', { name: 'Mở duyệt' }))
    expect(await screen.findByTestId('order-DJ0001')).toBeInTheDocument()
  })
})
