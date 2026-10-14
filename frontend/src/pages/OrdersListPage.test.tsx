import { afterEach, describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
import { GallerySyncProvider } from '../context/GallerySyncContext'
import { ToastProvider } from '../context/ToastContext'
import { OrdersListPage } from './OrdersListPage'

afterEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  window.history.pushState({}, '', '/')
  vi.unstubAllGlobals()
})


// The admin list is served page-by-page by GET /orders/page. The tests keep describing the data as a
// flat `{ orders }` list on /api/orders; this adapter answers /orders/page the way the server would.
const TAB_STATES: Record<string, string[]> = {
  waiting: ['WAITING', 'OPEN_FOR_ALLOCATION', 'DISCOVERED', 'PENDING', 'OPEN'],
  doing: ['IN_PROGRESS', 'DOING', 'ASSIGNED'],
  review: ['QC_PENDING', 'RESULT_SUBMITTED', 'SUBMITTING_TO_SITE', 'REVIEW'],
  fix: ['REVISION', 'REVISION_REQUESTED', 'FIX'],
  done: ['DONE', 'CLAIMED_IMPORTED', 'COMPLETED', 'SKIPPED'],
}

function adminPageAdapter(handler: (url: string, ...rest: any[]) => any) {
  return (url: string, ...rest: any[]) => {
    if (!url.includes('/api/orders/page')) return handler(url, ...rest)
    const params = new URL(url, 'http://localhost').searchParams
    return Promise.resolve(handler('/api/orders', ...rest)).then(async (res: any) => {
      const all: any[] = ((await res.json()).orders ?? [])
      const tabOf = (o: any) => Object.keys(TAB_STATES).find((t) => TAB_STATES[t].includes((o.state || '').toUpperCase()))
      const tab = params.get('tab') || 'waiting'
      let items = all.filter((o) => tabOf(o) === tab)
      const doingSub = params.get('doing_sub')
      if (tab === 'doing' && doingSub === 'missing') items = items.filter((o) => o.template_missing)
      if (tab === 'doing' && doingSub === 'normal') items = items.filter((o) => !o.template_missing)
      const fixSub = params.get('fix_sub')
      if (tab === 'fix' && fixSub === 'pending') items = items.filter((o) => !o.fix_approved_by_admin && !o.fix_rejected_by_admin)
      if (tab === 'fix' && fixSub === 'approved') items = items.filter((o) => o.fix_approved_by_admin)
      if (tab === 'fix' && fixSub === 'rejected') items = items.filter((o) => o.fix_rejected_by_admin)
      const q = (params.get('q') || '').toLowerCase()
      if (q) items = items.filter((o) => `${o.external_order_id} ${o.product_name ?? ''}`.toLowerCase().includes(q))
      const psf = (params.get('platform_status') || '').toLowerCase()
      if (psf) items = items.filter((o) => ((o.platform_status || '').toLowerCase().trim() === psf) || (psf === 'unspecified' && !o.platform_status))
      const tabAll = all.filter((o) => tabOf(o) === tab)
      const synced = (o: any) => (o.product_image_urls?.length ?? 0) > 1
      if (params.get('fix_returned') === 'true') items = items.filter((o) => (o.fix_return_count || 0) > 0)
      if (params.get('synced_images') === 'true') items = items.filter(synced)
      const count = (t: string) => all.filter((o) => tabOf(o) === t).length
      const body = {
        items,
        total: items.length,
        page: 1,
        page_size: 100,
        counts: {
          waiting: count('waiting'), doing: count('doing'), review: count('review'), fix: count('fix'), done: count('done'),
          doing_missing: all.filter((o) => tabOf(o) === 'doing' && o.template_missing).length,
          doing_normal: all.filter((o) => tabOf(o) === 'doing' && !o.template_missing).length,
          fix_pending: all.filter((o) => tabOf(o) === 'fix' && !o.fix_approved_by_admin && !o.fix_rejected_by_admin).length,
          fix_approved: all.filter((o) => tabOf(o) === 'fix' && o.fix_approved_by_admin).length,
          fix_rejected: all.filter((o) => tabOf(o) === 'fix' && o.fix_rejected_by_admin).length,
        },
        aux: { synced_images: tabAll.filter(synced).length, fix_returned: tabAll.filter((o) => (o.fix_return_count || 0) > 0).length },
      }
      return { ok: true, status: 200, json: async () => body }
    })
  }
}

describe('OrdersListPage', () => {
  it('renders orders and Print status filter for admin', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: '1', role: 'admin', full_name: 'Admin' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'a1',
                  external_order_id: 'DJ1',
                  product_name: 'Dallas Sport Tank Top',
                  state: 'DISCOVERED',
                  batch_id: null,
                  sku: 'SKU1',
                  thumbnail_url: null,
                  platform_status: 'waiting',
                  order_created_at_ext: '2026-09-10T14:28:00',
                  deadline_at_ext: null,
                  created_at: '2026-01-01T00:00:00',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
    )

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )
    await waitFor(() => expect(screen.getByText('DJ1')).toBeInTheDocument())
    expect(screen.getAllByText('Waiting').length).toBeGreaterThan(0)
    expect(screen.getByText('Order At')).toBeInTheDocument()
    expect(screen.getByText('21:28:00')).toBeInTheDocument()
    expect(screen.getByText('10/09/2026')).toBeInTheDocument()
    expect(screen.getByText('Tất cả trạng thái Print')).toBeInTheDocument()
  })

  it('does not let stale tab filters hide Doing or Fix orders', async () => {
    localStorage.setItem(
      'tacahu:view-state:v1:orders-list:admin',
      JSON.stringify({
        adminTab: 'doing',
        adminDoingSubFilter: 'missing',
        adminFixSubFilter: 'approved',
        statusFilter: 'REVIEW',
        platformStatusFilter: 'review',
        dateFrom: '2099-01-01',
        dateTo: '2099-01-31',
        currentPage: 4,
      }),
    )
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ id: 'admin-stale-filter', role: 'admin', full_name: 'Admin' }) })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/users')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => [] })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'doing-visible',
                  external_order_id: 'DJ-DOING-VISIBLE',
                  product_name: 'Doing order visible',
                  state: 'IN_PROGRESS',
                  template_missing: false,
                  platform_status: 'doing',
                  created_at: '2026-09-22T00:00:00Z',
                },
                {
                  id: 'fix-visible',
                  external_order_id: 'DJ-FIX-VISIBLE',
                  product_name: 'Fix order visible',
                  state: 'REVISION',
                  fix_approved_by_admin: false,
                  fix_rejected_by_admin: false,
                  platform_status: 'fix',
                  created_at: '2026-09-22T00:00:00Z',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })),
    )

    window.history.pushState({}, '', '/orders?tab=doing')
    render(
      <BrowserRouter>
        <AuthProvider><PlatformProvider><ToastProvider><GallerySyncProvider><OrdersListPage /></GallerySyncProvider></ToastProvider></PlatformProvider></AuthProvider>
      </BrowserRouter>,
    )

    // Legacy role-wide filters must not survive into the selected Doing tab.
    expect(await screen.findByText('DJ-DOING-VISIBLE')).toBeInTheDocument()

    fireEvent.change(screen.getByTitle('Lọc theo trạng thái trên Web mẹ'), { target: { value: 'review' } })
    await waitFor(() => expect(screen.queryByText('DJ-DOING-VISIBLE')).not.toBeInTheDocument())

    // Switching to Fix clears the incompatible Print/date/sub-filter state.
    fireEvent.click(screen.getByRole('button', { name: /Fix \(Cần sửa\)/i }))
    expect(await screen.findByText('DJ-FIX-VISIBLE')).toBeInTheDocument()
  })

  it('lets an admin filter the current tab to orders that have entered Fix', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ id: 'admin-fix-filter', role: 'admin', full_name: 'Admin' }) })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'fix-returned', external_order_id: 'DJ-FIX-X1', product_name: 'Đơn đã vào Fix', state: 'WAITING', fix_return_count: 1,
                  batch_id: null, sku: null, thumbnail_url: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
                },
                {
                  id: 'never-fixed', external_order_id: 'DJ-NO-FIX', product_name: 'Đơn chưa vào Fix', state: 'WAITING', fix_return_count: 0,
                  batch_id: null, sku: null, thumbnail_url: null, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })),
    )

    const view = render(
      <BrowserRouter>
        <AuthProvider><PlatformProvider><ToastProvider><GallerySyncProvider><OrdersListPage /></GallerySyncProvider></ToastProvider></PlatformProvider></AuthProvider>
      </BrowserRouter>,
    )

    await screen.findByText('DJ-FIX-X1')
    const fixReturnedButton = within(view.container).getByRole('button', { name: 'Lọc đơn đã vào Fix' })
    fireEvent.click(fixReturnedButton)

    expect(fixReturnedButton).toHaveAttribute('aria-pressed', 'true')
    // The server applies the filter, so the list changes after the next response.
    await waitFor(() => expect(within(view.container).queryByText('DJ-NO-FIX')).not.toBeInTheDocument())
    expect(within(view.container).getByText('DJ-FIX-X1')).toBeInTheDocument()
  })

  it('hides order code DJ1 and renders 4 tabs for designer', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'des1', role: 'designer', full_name: 'Designer 1' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'a1',
                  external_order_id: 'DJ1_SECRET_CODE',
                  product_name: 'Super Cool T-Shirt',
                  state: 'IN_PROGRESS',
                  template_missing: false,
                  batch_id: null,
                  sku: 'SKU1',
                  thumbnail_url: null,
                  order_created_at_ext: '2026-09-10T14:28:00',
                  deadline_at_ext: null,
                  created_at: '2026-01-01T00:00:00',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
    )

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    // Verify 5 tabs exist (Doing, Fix, Review, Waiting Update, Paid)
    await waitFor(() => expect(screen.getByText(/Đang làm/i)).toBeInTheDocument())
    expect(screen.getByText(/Cần Sửa Gấp \(Fix\)/i)).toBeInTheDocument()
    expect(screen.getAllByText(/Chờ duyệt/i).length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/Chờ Cập Nhật/i)).toBeInTheDocument()
    expect(screen.getByText(/Đã thanh toán/i)).toBeInTheDocument()
    expect(screen.queryByText(/Hoàn Thành \(Done\)/i)).not.toBeInTheDocument()

    // Verify To-do and All tasks tabs are removed
    expect(screen.queryByText(/Việc Cần Làm \(Todo\)/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Tất Cả Nhiệm Vụ/i)).not.toBeInTheDocument()

    // Verify order code is HIDDEN, but product name is visible
    expect(await screen.findByText('Super Cool T-Shirt')).toBeInTheDocument()
    expect(screen.queryByText('DJ1_SECRET_CODE')).not.toBeInTheDocument()

    // Verify action buttons
    expect(screen.getByText('Nộp bài')).toBeInTheDocument()
    expect(screen.getByText('Báo thiếu temp')).toBeInTheDocument()
  })

  it('only shows Admin-approved Fix orders in the designer Fix tab', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'des-fix', role: 'designer', full_name: 'Designer Fix' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'fix-unreleased', external_order_id: 'DJ-HIDDEN-FIX', product_name: 'Fix chưa duyệt',
                  state: 'REVISION', fix_approved_by_admin: false, template_missing: false,
                  batch_id: null, sku: null, thumbnail_url: null, created_at: '2026-01-01T00:00:00Z',
                },
                {
                  id: 'fix-approved', external_order_id: 'DJ-VISIBLE-FIX', product_name: 'Fix đã duyệt',
                  state: 'REVISION', fix_approved_by_admin: true, template_missing: false,
                  batch_id: null, sku: null, thumbnail_url: null, created_at: '2026-01-01T00:00:00Z',
                },
                {
                  id: 'fix-approved-paid', external_order_id: 'DJ-PAID-FIX', product_name: 'Fix gấp đã thanh toán',
                  state: 'REVISION', fix_approved_by_admin: true, is_paid: true, template_missing: false,
                  batch_id: null, sku: null, thumbnail_url: null, created_at: '2026-01-01T00:00:00Z',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })),
    )

    render(
      <BrowserRouter>
        <AuthProvider><PlatformProvider><ToastProvider><GallerySyncProvider><OrdersListPage /></GallerySyncProvider></ToastProvider></PlatformProvider></AuthProvider>
      </BrowserRouter>,
    )

    await waitFor(() => expect(screen.getByText(/Cần Sửa Gấp \(Fix\)/i)).toBeInTheDocument())
    fireEvent.click(screen.getByText(/Cần Sửa Gấp \(Fix\)/i))
    expect(await screen.findByText('Fix đã duyệt')).toBeInTheDocument()
    expect(screen.getByText('Fix gấp đã thanh toán')).toBeInTheDocument()
    expect(screen.queryByText('Fix chưa duyệt')).not.toBeInTheDocument()
  })

  it('renders Thời Gian column and Fix tab action buttons for Admin', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'admin1', role: 'admin', full_name: 'Admin User' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/users')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => [
              { id: 'des1', username: 'des1', full_name: 'Designer One', role: 'designer' },
            ],
          })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'fix1',
                  external_order_id: 'DJ999',
                  product_name: 'Fix Needed Hoodie',
                  state: 'REVISION',
                  work_domain: 'duplicate',
                  batch_id: null,
                  sku: 'SKU999',
                  thumbnail_url: null,
                  platform_status: 'fix',
                  assigned_designer_name: 'Designer One',
                  status_changed_at: '2026-09-11T07:30:00Z',
                  order_created_at_ext: '2026-09-10T14:28:00',
                  deadline_at_ext: null,
                  created_at: '2026-09-10T00:00:00Z',
                  note_outsource: 'Please resize back logo',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
    )

    // Simulate opening with tab=fix
    window.history.pushState({}, '', '/orders?tab=fix')

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    await waitFor(() => expect(screen.getByText('DJ999')).toBeInTheDocument())

    // Verify Thời Gian column header exists
    expect(screen.getByText('Thời Gian')).toBeInTheDocument()
    expect(screen.getByText('Lọc thời gian:')).toBeInTheDocument()

    // Verify Fix Tab action buttons exist: "Chấp nhận Fix" and "Từ chối Fix"
    expect(screen.getByText('Chấp nhận Fix')).toBeInTheDocument()
    expect(screen.getByText('Từ chối Fix')).toBeInTheDocument()

    // Verify old manual approve/fix buttons do NOT exist
    expect(screen.queryByText('Duyệt Done')).not.toBeInTheDocument()
  })

  it('renders and filters by synced images button', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: '1', role: 'admin', full_name: 'Admin' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'ord-synced',
                  external_order_id: 'ORDER-SYNCED-01',
                  product_name: 'Product With Multi Gallery',
                  state: 'WAITING',
                  batch_id: null,
                  sku: 'SKU1',
                  thumbnail_url: 'https://thumb.url/1.png',
                  product_image_urls: ['https://thumb.url/1.png', 'https://thumb.url/2.png'],
                  platform_status: 'waiting',
                  order_created_at_ext: '2026-09-10T14:28:00',
                  deadline_at_ext: null,
                  created_at: '2026-01-01T00:00:00',
                },
                {
                  id: 'ord-unsynced',
                  external_order_id: 'ORDER-UNSYNCED-02',
                  product_name: 'Product Unsynced',
                  state: 'WAITING',
                  batch_id: null,
                  sku: 'SKU2',
                  thumbnail_url: 'https://thumb.url/thumb.png',
                  product_image_urls: null,
                  platform_status: 'waiting',
                  order_created_at_ext: '2026-09-10T14:28:00',
                  deadline_at_ext: null,
                  created_at: '2026-01-01T00:00:00',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
    )

    window.history.pushState({}, '', '/orders?tab=waiting')

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    await waitFor(() => expect(screen.getByText('ORDER-SYNCED-01')).toBeInTheDocument())
    expect(screen.getByText('ORDER-UNSYNCED-02')).toBeInTheDocument()

    // Synced filter button exists and shows count 1
    const syncedFilterBtn = screen.getByRole('button', { name: /Đơn đã đồng bộ ảnh/i })
    expect(syncedFilterBtn).toBeInTheDocument()
    expect(syncedFilterBtn).toHaveTextContent('1')

    // Click filter button
    fireEvent.click(syncedFilterBtn)

    // Now only the synced order should be present
    await waitFor(() => {
      expect(screen.getByText('ORDER-SYNCED-01')).toBeInTheDocument()
      expect(screen.queryByText('ORDER-UNSYNCED-02')).not.toBeInTheDocument()
    })
  })

  it('renders Fix sub-filters and proper status badges for approved/rejected fix orders', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'admin1', role: 'admin', full_name: 'Admin User' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/users')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => [
              { id: 'des1', username: 'des1', full_name: 'Designer One', role: 'designer' },
            ],
          })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'fix-pending',
                  external_order_id: 'DJ-PENDING',
                  product_name: 'Fix Pending Item',
                  state: 'REVISION',
                  fix_approved_by_admin: false,
                  fix_rejected_by_admin: false,
                  platform_status: 'fix',
                  assigned_designer_name: 'Designer One',
                  created_at: '2026-09-10T00:00:00Z',
                },
                {
                  id: 'fix-approved',
                  external_order_id: 'DJ-APPROVED',
                  product_name: 'Fix Approved Item',
                  state: 'REVISION',
                  fix_approved_by_admin: true,
                  fix_rejected_by_admin: false,
                  platform_status: 'fix',
                  assigned_designer_name: 'Designer One',
                  created_at: '2026-09-10T00:00:00Z',
                },
                {
                  id: 'fix-rejected',
                  external_order_id: 'DJ-REJECTED',
                  product_name: 'Fix Rejected Item',
                  state: 'REVISION',
                  fix_approved_by_admin: false,
                  fix_rejected_by_admin: true,
                  platform_status: 'fix',
                  assigned_designer_name: 'Designer One',
                  created_at: '2026-09-10T00:00:00Z',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error())
      }))
    )

    window.history.pushState({}, '', '/orders?tab=fix')

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    await waitFor(() => expect(screen.getByText('DJ-PENDING')).toBeInTheDocument())
    expect(screen.getByText('DJ-APPROVED')).toBeInTheDocument()
    expect(screen.getByText('DJ-REJECTED')).toBeInTheDocument()

    // Verify sub-filter buttons exist
    expect(screen.getByText('Chưa lựa chọn')).toBeInTheDocument()
    expect(screen.getByText('Đã chấp nhận Fix')).toBeInTheDocument()
    expect(screen.getByText('Đã từ chối Fix')).toBeInTheDocument()

    // Verify badges and action buttons
    expect(screen.getByText('Chấp nhận Fix')).toBeInTheDocument()
    expect(screen.getByText('Từ chối Fix')).toBeInTheDocument()
    expect(screen.getByText('Đã gửi fix cho des')).toBeInTheDocument()
    expect(screen.getByText('Đã từ chối fix')).toBeInTheDocument()
  })

  it('renders 3 tabs and duplicate check actions for support role', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'supp1', role: 'support', full_name: 'Support User' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/orders/duplicate-check-status')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ updated: 1 }),
          })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'supp-order-1',
                  external_order_id: 'DJ-SUPP-1',
                  product_name: 'Support Product',
                  state: 'DISCOVERED',
                  work_domain: 'standard',
                  duplicate_check_status: 'uncheck',
                  platform_status: 'waiting',
                  created_at: '2026-09-18T00:00:00Z',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
    )

    window.history.pushState({}, '', '/orders')

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    await waitFor(() => expect(screen.getByText('DJ-SUPP-1')).toBeInTheDocument())

    // Check Support 3 tabs
    expect(screen.getByRole('button', { name: /Chưa kiểm tra/i })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Trùng lặp/i }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: /Không trùng lặp/i }).length).toBeGreaterThan(0)

    // Check action buttons for Support on Chưa kiểm tra tab
    expect(screen.getAllByRole('button', { name: /Trùng lặp/i }).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('button', { name: /Không trùng lặp/i }).length).toBeGreaterThan(0)

    // Verify "Quét Đơn Mới" is NOT present for Support
    expect(screen.queryByText(/Quét Đơn Mới/i)).not.toBeInTheDocument()
  })

  it('puts every Support order in exactly one tab: an untagged assigned order is read-only in Đang làm', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'supp1', role: 'support', full_name: 'Support User' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/support-compare/status')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ enabled: true, new_orders: 2, handleable_orders: 3 }),
          })
        }
        if (url.includes('/api/support-compare/handle')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ handled_count: 3 }) })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'o-waiting',
                  external_order_id: 'DJ-WAITING',
                  product_name: 'Waiting Product',
                  state: 'WAITING',
                  work_domain: 'standard',
                  duplicate_check_status: 'uncheck',
                  created_at: '2026-09-18T00:00:00Z',
                },
                {
                  id: 'o-doing',
                  external_order_id: 'DJ-DOING',
                  product_name: 'Doing Product',
                  state: 'IN_PROGRESS',
                  work_domain: 'standard',
                  duplicate_check_status: 'uncheck',
                  created_at: '2026-09-18T00:00:00Z',
                },
                {
                  id: 'o-review',
                  external_order_id: 'DJ-REVIEW',
                  product_name: 'Review Product',
                  state: 'QC_PENDING',
                  work_domain: 'standard',
                  duplicate_check_status: 'non_duplicate',
                  created_at: '2026-09-18T00:00:00Z',
                },
                {
                  id: 'o-duplicate-doing',
                  external_order_id: 'DJ-DUP-DOING',
                  product_name: 'Duplicate Doing Product',
                  state: 'IN_PROGRESS',
                  work_domain: 'duplicate',
                  duplicate_check_status: 'duplicate',
                  created_at: '2026-09-18T00:00:00Z',
                },
              ],
              submitted_count: 7,
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
    )

    window.history.pushState({}, '', '/orders')

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    // Only the untagged Waiting order is in Chưa kiểm tra; the untagged order Admin already
    // assigned is in Đang làm and cannot be tagged any more.
    await waitFor(() => expect(screen.getByText('DJ-WAITING')).toBeInTheDocument())
    expect(screen.queryByText('DJ-DOING')).not.toBeInTheDocument()
    expect(screen.getAllByTitle('Đánh dấu đơn này là Trùng lặp')).toHaveLength(1)
    // The four tabs (1 + 1 + 1 + 1) add up to the list; handed-in orders are only a number.
    expect(screen.getByTestId('support-totals')).toHaveTextContent('Tổng 4 tab: 4 · Đã nộp bài (đã ẩn): 7 · Tổng cộng: 11')
    // Web entry for the same job as Telegram /check.
    expect(await screen.findByRole('button', { name: /Kiểm tra trùng \(2\)/ })).toBeInTheDocument()
    // ...and for Telegram /handle: compared orders with no duplicate move to Không trùng lặp.
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(await screen.findByRole('button', { name: /Chuyển không trùng \(3\)/ }))
    await waitFor(() =>
      expect(
        (fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls.some(
          ([url, init]) => url.includes('/api/support-compare/handle') && init?.method === 'POST',
        ),
      ).toBe(true),
    )
    // Classified non_duplicate order is NOT in Tab 1 ("Chưa kiểm tra")
    expect(screen.queryByText('DJ-REVIEW')).not.toBeInTheDocument()

    // Classified orders remain visible in their own tabs after leaving
    // Waiting, but their Support controls are read-only.
    fireEvent.click(screen.getByRole('button', { name: /^Trùng lặp1$/i }))
    expect(await screen.findByText('DJ-DUP-DOING')).toBeInTheDocument()
    // No "Chỉ xem" text any more: a duplicate card nobody has taken can be put back (button lit).
    expect(screen.queryByText('Chỉ xem')).not.toBeInTheDocument()
    expect(screen.getByTitle('Bấm để đưa đơn về tab Chưa xử lý')).toBeEnabled()
    // A free duplicate card can be taken for the in-house designer ("Lấy").
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    fireEvent.click(screen.getByRole('button', { name: 'Lấy' }))
    await waitFor(() =>
      expect(
        (fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls.some(
          ([url, init]) => url.includes('/api/orders/support-take') && init?.method === 'POST',
        ),
      ).toBe(true),
    )

    fireEvent.click(screen.getByRole('button', { name: /^Không trùng lặp1$/i }))
    expect(await screen.findByText('DJ-REVIEW')).toBeInTheDocument()
    // An unchecked Doing order stays in Chưa kiểm tra: only explicitly classified orders are here.
    expect(screen.queryByText('DJ-DOING')).not.toBeInTheDocument()
    // Orders that already moved on (QC) show the tag dimmed and disabled, without any text.
    expect(screen.queryByText('Chỉ xem')).not.toBeInTheDocument()
    const dimmed = screen.getAllByTitle('Đơn đã sang bước xử lý khác nên không đưa về Chưa xử lý được')
    expect(dimmed.length).toBeGreaterThanOrEqual(1)
    dimmed.forEach((button) => expect(button).toBeDisabled())

    // Support can search by order code (it sees the code), not only by product name.
    fireEvent.click(screen.getByRole('button', { name: /^Trùng lặp1$/i }))
    const search = screen.getByPlaceholderText('Tìm theo Mã Đơn, Tên SP...')
    fireEvent.change(search, { target: { value: 'dj-dup-doing' } })
    expect(await screen.findByText('DJ-DUP-DOING')).toBeInTheDocument()
    fireEvent.change(search, { target: { value: '' } })

    fireEvent.click(screen.getByRole('button', { name: /^Đang làm1$/i }))
    expect(await screen.findByText('DJ-DOING')).toBeInTheDocument()
    expect(screen.queryByText('DJ-DUP-DOING')).not.toBeInTheDocument()  // a tag wins: it stays in Trùng lặp
    expect(screen.getAllByText('Chỉ xem').length).toBeGreaterThanOrEqual(1)  // the Doing tab keeps its label
    expect(screen.queryByTitle('Đánh dấu đơn này là Trùng lặp')).not.toBeInTheDocument()
  })

  it('lets Support put an untaken classified order back into Chưa xử lý after a confirmation, and dims the taken ones', async () => {
    const orders = [
      { id: 'o-free', external_order_id: 'DJ-FREE', product_name: 'Free', state: 'WAITING', work_domain: 'standard', duplicate_check_status: 'non_duplicate', assigned_designer_name: null, version: 3, created_at: '2026-09-18T00:00:00Z' },
      { id: 'o-mine', external_order_id: 'DJ-TAKEN', product_name: 'Taken', state: 'WAITING', work_domain: 'standard', duplicate_check_status: 'non_duplicate', assigned_designer_name: 'Lan Anh', version: 1, created_at: '2026-09-18T00:00:00Z' },
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string, init?: RequestInit) => {
        const ok = (body: unknown) => Promise.resolve({ ok: true, status: 200, json: async () => body })
        if (url.includes('/api/me')) return ok({ id: 'supp1', role: 'support', full_name: 'Support User' })
        if (url.includes('/api/platforms')) return ok({ platforms: [] })
        if (url.includes('/api/support-compare/status')) return ok({ enabled: true, new_orders: 0, handleable_orders: 0 })
        if (url.includes('/api/orders/return-to-unchecked') && init?.method === 'POST') return ok({ changed_count: 1 })
        if (url.includes('/api/orders')) return ok({ orders })
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })),
    )
    window.history.pushState({}, '', '/orders?support_tab=non_duplicate')
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>,
    )

    await waitFor(() => expect(screen.getByText('DJ-FREE')).toBeInTheDocument())
    // A taken order: the designer icon is shown (name only in the tooltip) and the tag is dimmed.
    expect(screen.getByTitle('Đã lấy · Lan Anh')).toBeInTheDocument()
    expect(screen.queryByText(/Đã lấy/)).not.toBeInTheDocument()
    expect(screen.getByTitle('Đơn đã có designer đảm nhận nên không đưa về Chưa xử lý được')).toBeDisabled()

    // A free order: lit and clickable; it asks first, and cancelling changes nothing.
    const free = screen.getByTitle('Bấm để đưa đơn về tab Chưa xử lý')
    expect(free).toBeEnabled()
    const posts = () =>
      (fetch as unknown as { mock: { calls: [string, RequestInit?][] } }).mock.calls.filter(([url]) => url.includes('/api/orders/return-to-unchecked'))
    fireEvent.click(free)
    expect(confirm).toHaveBeenLastCalledWith(expect.stringContaining('Bạn có chắc muốn đưa đơn DJ-FREE về lại tab Chưa xử lý không?'))
    expect(posts()).toHaveLength(0)

    confirm.mockReturnValue(true)
    fireEvent.click(free)
    await waitFor(() => expect(posts()).toHaveLength(1))
    expect(JSON.parse(String(posts()[0][1]?.body))).toEqual({ order_ids: ['o-free'], expected_versions: { 'o-free': 3 } })
  })

  it('renders orange exclamation badge on Admin across all tabs when uncheck, and supports Hủy chia', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'admin1', role: 'admin', full_name: 'Admin User' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/assignments/revoke')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ message: 'Đã hủy chia đơn thành công cho 1 đơn hàng.', revoked_count: 1 }),
          })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'o-doing-1',
                  external_order_id: 'DJ-DOING-1',
                  product_name: 'Doing Shirt',
                  state: 'IN_PROGRESS',
                  work_domain: 'standard',
                  duplicate_check_status: 'uncheck',
                  created_at: '2026-09-18T00:00:00Z',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
    )

    window.history.pushState({}, '', '/orders?tab=doing')

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    await waitFor(() => expect(screen.getByText('DJ-DOING-1')).toBeInTheDocument())
    // Exclamation mark badge in Doing tab
    expect(screen.getByText('Chưa kiểm tra')).toBeInTheDocument()

    // Revoke button in Doing tab
    const revokeBtn = screen.getByRole('button', { name: /Hủy chia/i })
    expect(revokeBtn).toBeInTheDocument()
    fireEvent.click(revokeBtn)
  })

  it('pre-selects assigned designer in modal and supports Hủy phân công', async () => {
    let revokeCalledWith: any = null
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string, opts?: any) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'admin1', role: 'admin', full_name: 'Admin User' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/users')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => [
              { id: 'des-1', username: 'des1', full_name: 'Designer One', role: 'designer' },
              { id: 'des-2', username: 'des2', full_name: 'Designer Two', role: 'designer' },
            ],
          })
        }
        if (url.includes('/api/assignments/revoke')) {
          revokeCalledWith = JSON.parse(opts.body)
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ message: 'Đã hủy phân công cho đơn DJ4020336.', revoked_count: 1 }),
          })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'o-waiting-1',
                  external_order_id: 'DJ4020336',
                  product_name: 'Bowling Hawaiian Shirt',
                  state: 'WAITING',
                  work_domain: 'standard',
                  duplicate_check_status: 'uncheck',
                  assigned_designer_name: 'des1',
                  assigned_designer_id: 'des-1',
                  created_at: '2026-09-18T00:00:00Z',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
    )

    window.history.pushState({}, '', '/orders?tab=waiting')

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    await waitFor(() => expect(screen.getByText('DJ4020336')).toBeInTheDocument())

    // Click on designer badge "des1"
    const desBadge = screen.getByText('des1')
    expect(desBadge).toBeInTheDocument()
    fireEvent.click(desBadge)

    // Modal popup should open
    await waitFor(() => expect(screen.getByRole('heading', { name: /Phân Công Designer/i })).toBeInTheDocument())
    expect(screen.getByText(/Hiện đang phân công:/i)).toBeInTheDocument()

    // First select dropdown should pre-select des-1
    const designerSelect = screen.getByRole('combobox', { name: /Chọn Designer Tacahu/i }) as HTMLSelectElement
    expect(designerSelect.value).toBe('des-1')

    // "Hủy phân công" button should be present
    const unassignBtn = screen.getByRole('button', { name: /Hủy phân công/i })
    expect(unassignBtn).toBeInTheDocument()

    // Click "Hủy phân công"
    fireEvent.click(unassignBtn)
    await waitFor(() => expect(revokeCalledWith).toEqual({ order_ids: ['o-waiting-1'] }))
  })

  it('renders CopyableProductName and handles inline design submission for designer', async () => {
    let patchedStateBody: any = null
    let assignmentResultBody: any = null

    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string, init?: RequestInit) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'des10', role: 'designer', full_name: 'Test Designer' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/assignments/assign-99/results')) {
          assignmentResultBody = JSON.parse(init?.body as string)
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ success: true }) })
        }
        if (url.includes('/api/orders/order-99/state')) {
          patchedStateBody = JSON.parse(init?.body as string)
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ success: true }) })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'order-99',
                  assignment_id: 'assign-99',
                  external_order_id: 'ORD-DESIGN-99',
                  product_name: 'Awesome Vintage T-Shirt',
                  state: 'IN_PROGRESS',
                  template_missing: false,
                  batch_id: null,
                  sku: 'SKU99',
                  thumbnail_url: null,
                  order_created_at_ext: '2026-09-10T14:28:00',
                  deadline_at_ext: null,
                  created_at: '2026-01-01T00:00:00',
                  drive_url: null,
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
    )

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    // Wait for product name to be displayed
    await waitFor(() => expect(screen.getByText('Awesome Vintage T-Shirt')).toBeInTheDocument())

    // Product name button has copy title
    const copyButton = screen.getByTitle('Click để sao chép tên sản phẩm')
    expect(copyButton).toBeInTheDocument()

    // Inline input with placeholder
    const input = screen.getByPlaceholderText('Dán link thiết kế (Drive, Canva, DropBox...)') as HTMLInputElement
    expect(input).toBeInTheDocument()

    // Fill in link
    fireEvent.change(input, { target: { value: 'https://drive.google.com/file/d/123/view' } })
    expect(input.value).toBe('https://drive.google.com/file/d/123/view')

    // Click "Nộp bài"
    const submitBtn = screen.getByRole('button', { name: /Nộp bài/i })
    expect(submitBtn).toBeInTheDocument()
    fireEvent.click(submitBtn)

    await waitFor(() => {
      expect(assignmentResultBody).toBeTruthy()
      expect(assignmentResultBody.drive_url).toBe('https://drive.google.com/file/d/123/view')
      expect(patchedStateBody).toBeNull()
    })
  })

  it('renders Chia đơn nhanh button for admin on waiting tab and opens quick distribute modal', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(adminPageAdapter((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              id: 'u-admin',
              username: 'admin1',
              role: 'admin',
              full_name: 'Super Admin',
            }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/users')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => [
              { id: 'des-1', username: 'designer_a', full_name: 'Designer A', role: 'designer' },
            ],
          })
        }
        if (url.includes('/api/orders')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              orders: [
                {
                  id: 'ord-wait-1',
                  external_order_id: 'DJ-W1',
                  product_name: 'Summer Tee',
                  state: 'WAITING',
                  duplicate_check_status: 'uncheck',
                  created_at: '2026-01-01T00:00:00',
                },
              ],
            }),
          })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      }))
    )

    render(
      <BrowserRouter>
        <AuthProvider>
          <PlatformProvider>
            <ToastProvider>
              <GallerySyncProvider>
                <OrdersListPage />
              </GallerySyncProvider>
            </ToastProvider>
          </PlatformProvider>
        </AuthProvider>
      </BrowserRouter>
    )

    await waitFor(() => expect(screen.getByText('DJ-W1')).toBeInTheDocument())

    // "Chia đơn nhanh" button should exist
    const quickBtn = screen.getByRole('button', { name: /Chia đơn nhanh/i })
    expect(quickBtn).toBeInTheDocument()

    // Click it to open modal
    fireEvent.click(quickBtn)

    expect(screen.getByText('Chia Đơn Nhanh Cho Designer')).toBeInTheDocument()
    expect(screen.getByText('Designer A')).toBeInTheDocument()
  })
  it('shows a recently loaded admin page from the cache instead of loading it again', async () => {
    const fetchMock = vi.fn(adminPageAdapter((url: string) => {
      if (url.includes('/api/me')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ id: 'admin-cache', role: 'admin', full_name: 'Admin' }) })
      }
      if (url.includes('/api/platforms')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
      }
      if (url.includes('/api/users')) {
        return Promise.resolve({ ok: true, status: 200, json: async () => [] })
      }
      if (url.includes('/api/orders')) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: async () => ({
            orders: [{ id: 'c1', external_order_id: 'DJ-CACHED', product_name: 'Cached order', state: 'IN_PROGRESS', created_at: '2026-09-22T00:00:00Z' }],
          }),
        })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    }))
    vi.stubGlobal('fetch', fetchMock)
    const pageCalls = () => fetchMock.mock.calls.filter(([url]) => String(url).includes('/api/orders/page')).length
    const tree = (
      <BrowserRouter>
        <AuthProvider><PlatformProvider><ToastProvider><GallerySyncProvider><OrdersListPage /></GallerySyncProvider></ToastProvider></PlatformProvider></AuthProvider>
      </BrowserRouter>
    )

    window.history.pushState({}, '', '/orders?tab=doing')
    const first = render(tree)
    expect(await screen.findByText('DJ-CACHED')).toBeInTheDocument()
    expect(pageCalls()).toBe(1)
    first.unmount()

    // Coming back from an order's detail: same page, straight from the cache, no new request.
    render(tree)
    expect(await screen.findByText('DJ-CACHED')).toBeInTheDocument()
    expect(pageCalls()).toBe(1)
  })
})
