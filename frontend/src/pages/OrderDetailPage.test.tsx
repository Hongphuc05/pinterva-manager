import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { PlatformProvider } from '../auth/PlatformContext'
import { GallerySyncProvider } from '../context/GallerySyncContext'
import { OrderDetailPage } from './OrderDetailPage'

describe('OrderDetailPage', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
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
        if (url.includes('/api/sync-jobs')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => null })
        }
        if (url.includes('/api/orders/pending-galleries')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ orders: [] }) })
        }
        if (url.includes('/api/orders/')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              order: {
                id: 'a1',
                external_order_id: 'DJ1',
                state: 'DISCOVERED',
                product_name: 'Test Mug',
                thumbnail_url: null,
                sku: 'SKU1',
                product_category: null,
                product_variants: null,
                product_skus: [],
                multiple_design: false,
                double_sided: false,
                deadline_at_ext: null,
                note_outsource: '',
                custom_config: null,
                design_tool_url: null,
                product_image_urls: [],
                created_at: '2026-01-01T00:00:00',
              },
              history: [
                {
                  id: 'event-1',
                  created_at: '2026-01-01T01:00:00',
                  from_state: 'IN_PROGRESS',
                  to_state: 'QC_PENDING',
                  actor_id: 'des1',
                  actor_name: 'Designer 1',
                  actor_role: 'designer',
                  action: 'SUBMIT_REVIEW',
                  description: 'Designer 1 nộp bài sang Review',
                  evidence: { drive_link: 'https://drive.google.com/test-file' },
                },
              ],
            }),
          })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
      })
    )
  })

  it('renders order fields', async () => {
    render(
      <AuthProvider>
        <PlatformProvider>
          <GallerySyncProvider>
            <MemoryRouter initialEntries={['/orders/a1']}>
              <Routes>
                <Route path="/orders/:id" element={<OrderDetailPage />} />
              </Routes>
            </MemoryRouter>
          </GallerySyncProvider>
        </PlatformProvider>
      </AuthProvider>
    )
    await waitFor(() => expect(screen.getAllByText(/Test Mug/).length).toBeGreaterThan(0))
    expect(screen.getByText(/Mẫu hàng \/ SKU/)).toBeInTheDocument()
    expect(screen.getAllByText(/1 mẫu hàng/).length).toBeGreaterThan(0)
    expect(screen.getByText('DJ1')).toBeInTheDocument()
  })

  it('hides order code DJ1 and displays product name for designer', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
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
        if (url.includes('/api/sync-jobs')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => null })
        }
        if (url.includes('/api/orders/pending-galleries')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ orders: [] }) })
        }
        if (url.includes('/api/orders/')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              order: {
                id: 'a1',
                external_order_id: 'DJ1_SECRET_CODE',
                state: 'IN_PROGRESS',
                product_name: 'Secret Hoodie Design',
                thumbnail_url: null,
                sku: 'SKU1',
                product_category: null,
                product_variants: null,
                product_skus: [],
                multiple_design: false,
                double_sided: false,
                deadline_at_ext: null,
                note_outsource: '',
                custom_config: null,
                design_tool_url: null,
                product_image_urls: [],
                created_at: '2026-01-01T00:00:00',
              },
              history: [],
            }),
          })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
      })
    )

    render(
      <AuthProvider>
        <PlatformProvider>
          <GallerySyncProvider>
            <MemoryRouter initialEntries={['/orders/a1']}>
              <Routes>
                <Route path="/orders/:id" element={<OrderDetailPage />} />
              </Routes>
            </MemoryRouter>
          </GallerySyncProvider>
        </PlatformProvider>
      </AuthProvider>
    )

    await waitFor(() => expect(screen.getByText(/Secret Hoodie Design/)).toBeInTheDocument())
    // Verify order code is HIDDEN from designer
    expect(screen.queryByText('DJ1_SECRET_CODE')).not.toBeInTheDocument()
  })

  it('does not render submitted version history for a designer', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
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
        if (url.includes('/api/sync-jobs')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => null })
        }
        if (url.includes('/api/orders/pending-galleries')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ orders: [] }) })
        }
        if (url.includes('/api/orders/')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              order: {
                id: 'a1',
                external_order_id: 'DJ1',
                assignment_id: 'asg-1',
                state: 'QC_PENDING',
                product_name: 'Custom Mug',
                thumbnail_url: null,
                sku: 'SKU1',
                product_category: null,
                product_variants: null,
                product_skus: [],
                multiple_design: false,
                double_sided: false,
                deadline_at_ext: null,
                note_outsource: '',
                custom_config: null,
                design_tool_url: null,
                product_image_urls: [],
                created_at: '2026-01-01T00:00:00',
                result_versions: [
                  { id: 'v1', drive_url: '1', version_marker: 1, submitted_at: '2026-01-01T00:00:00', qc_feedback: null },
                  { id: 'v2', drive_url: 'https://drive.google.com/test-file', version_marker: 2, submitted_at: '2026-01-01T01:00:00', qc_feedback: null }
                ]
              },
              history: [
                {
                  id: 'event-1',
                  created_at: '2026-01-01T01:00:00',
                  from_state: 'IN_PROGRESS',
                  to_state: 'QC_PENDING',
                  actor_id: 'des1',
                  actor_name: 'Designer 1',
                  actor_role: 'designer',
                  action: 'SUBMIT_REVIEW',
                  description: 'Designer 1 nộp bài sang Review',
                  evidence: { drive_link: 'https://drive.google.com/test-file' },
                },
              ],
            }),
          })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
      })
    )

    render(
      <AuthProvider>
        <PlatformProvider>
          <GallerySyncProvider>
            <MemoryRouter initialEntries={['/orders/a1']}>
              <Routes>
                <Route path="/orders/:id" element={<OrderDetailPage />} />
              </Routes>
            </MemoryRouter>
          </GallerySyncProvider>
        </PlatformProvider>
      </AuthProvider>
    )

    await waitFor(() => expect(screen.getByText('Custom Mug')).toBeInTheDocument())
    expect(screen.queryByText('Lịch sử các bản đã nộp (2)')).not.toBeInTheDocument()
    expect(screen.queryByText('Bản v1')).not.toBeInTheDocument()
    expect(screen.queryByText('Bản v2')).not.toBeInTheDocument()
    expect(screen.queryByText('https://drive.google.com/test-file')).not.toBeInTheDocument()
    expect(screen.queryByText(/Lịch Sử Tiến Độ & Hoạt Động/i)).not.toBeInTheDocument()
  })

  it('renders single Order At card and header variants (Type, Size) for designer while hiding SKU card', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({ id: 'des1', role: 'designer', full_name: 'phúc' }),
          })
        }
        if (url.includes('/api/platforms')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ platforms: [] }) })
        }
        if (url.includes('/api/sync-jobs')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => null })
        }
        if (url.includes('/api/orders/pending-galleries')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({ orders: [] }) })
        }
        if (url.includes('/api/orders/')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: async () => ({
              order: {
                id: 'a2',
                external_order_id: 'DJ4000',
                state: 'IN_PROGRESS',
                product_name: 'Insulated Monogram Lunch Box',
                thumbnail_url: null,
                sku: 'SKU99',
                product_category: 'Lunch Bags',
                product_variants: [
                  { name: 'Type', value: 'Fleece Blanket' },
                  { name: '| Size', value: '60" x 80"' },
                  { name: '| Size', value: '50" x 60"' },
                ],
                product_skus: [],
                multiple_design: false,
                double_sided: false,
                deadline_at_ext: '2026-09-18T04:15:46',
                order_created_at_ext: '2026-09-17T22:07:40',
                note_outsource: '',
                custom_config: null,
                design_tool_url: null,
                product_image_urls: [],
                created_at: '2026-09-17T22:07:40',
              },
              history: [],
            }),
          })
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
      })
    )

    render(
      <AuthProvider>
        <PlatformProvider>
          <GallerySyncProvider>
            <MemoryRouter initialEntries={['/orders/a2']}>
              <Routes>
                <Route path="/orders/:id" element={<OrderDetailPage />} />
              </Routes>
            </MemoryRouter>
          </GallerySyncProvider>
        </PlatformProvider>
      </AuthProvider>
    )

    await waitFor(() => expect(screen.getByText('Insulated Monogram Lunch Box')).toBeInTheDocument())

    // 1. Header shows Category and Variants (Type, Size)
    expect(screen.getByText('Lunch Bags')).toBeInTheDocument()
    expect(screen.getByText('Fleece Blanket')).toBeInTheDocument()
    expect(screen.getByText('60" x 80"')).toBeInTheDocument()
    expect(screen.getByText('50" x 60"')).toBeInTheDocument()
    expect(screen.getByText('Size:')).toBeInTheDocument()
    expect(screen.queryByText('| Size:')).not.toBeInTheDocument()

    // 2. Shows single Order At card
    expect(screen.getByText(/Thời Gian Khách Đặt \(Order At\)/i)).toBeInTheDocument()

    // 3. Old 3 cards and SKU card are hidden for designer
    expect(screen.queryByText(/Thời Hạn \(Deadline\)/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Ngày Phát Hiện \(Crawl\)/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/Mẫu Hàng Thiết Kế/i)).not.toBeInTheDocument()
  })
})
