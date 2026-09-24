import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { BrowserRouter } from 'react-router-dom'
import { ToastProvider } from '../context/ToastContext'
import { apiFetch } from '../api/client'
import { TelegramManagementPage } from './TelegramManagementPage'

vi.mock('../components/DashboardLayout', () => ({
  DashboardLayout: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}))

vi.mock('../api/client', () => ({
  apiFetch: vi.fn(),
  ApiError: class ApiError extends Error {},
}))

const apiFetchMock = vi.mocked(apiFetch)

const overview = {
  is_configured: true,
  bot_username: 'des_mana_bot',
  platform_id: 'platform-1',
  recipient_count: 2,
  designer_count: 1,
  support_count: 1,
  private_connected_count: 2,
  group_configured_count: 0,
  group_verified_count: 0,
  designers: [{
    id: 'designer-1',
    username: 'designer_one',
    full_name: 'Designer Một',
    role: 'designer',
    active: true,
    private_chat_id: '1001',
    private_username: 'designer_one_tg',
    private_connected: true,
    group_chat_id: null,
    group_title: null,
    group_type: null,
    group_configured: false,
    group_verified: false,
    group_verified_at: null,
    group_last_error: null,
    delivery_mode: 'private' as const,
    selected_chat_id: '1001',
    notifications_enabled: true,
  }, {
    id: 'support-1',
    username: 'support_one',
    full_name: 'Support Một',
    role: 'support',
    active: true,
    private_chat_id: '2001',
    private_username: 'support_one_tg',
    private_connected: true,
    group_chat_id: null,
    group_title: null,
    group_type: null,
    group_configured: false,
    group_verified: false,
    group_verified_at: null,
    group_last_error: null,
    delivery_mode: 'private' as const,
    selected_chat_id: '2001',
    notifications_enabled: true,
  }],
}

const templates = [{
  template_key: 'designer_new_order',
  audience: 'designer' as const,
  body: 'Sản phẩm: {{product_name}}',
  active: true,
  version: 1,
  updated_by_id: null,
  updated_at: null,
  placeholders: ['admin_note', 'deadline', 'product_name'],
}, {
  template_key: 'support_duplicate_match_candidate',
  audience: 'support' as const,
  body: 'Mã đơn cũ: {{matched_order_code}}',
  active: true,
  version: 1,
  updated_by_id: null,
  updated_at: null,
  placeholders: ['classifier', 'matched_order_code', 'matched_product_name', 'similarity'],
}]

describe('TelegramManagementPage', () => {
  beforeEach(() => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/telegram/admin/overview') return overview
      if (path === '/telegram/admin/templates') return templates
      if (path === '/telegram/admin/templates/designer_new_order/preview') {
        return { template_key: 'designer_new_order', rendered: '🚨 <b>CẢNH BÁO</b>\n<i>Ghi chú mẫu</i> <code>DJ0000000</code>' }
      }
      if (path === '/telegram/admin/templates/support_duplicate_match_candidate/preview') {
        return { template_key: 'support_duplicate_match_candidate', rendered: '🗂 <b>ẢNH ĐÃ CÓ TRONG KHO LỊCH SỬ</b>' }
      }
      throw new Error(`Unexpected API path: ${path}`)
    })
  })

  it('loads designer routing and sends group mapping update from the admin page', async () => {
    render(
      <BrowserRouter>
        <ToastProvider>
          <TelegramManagementPage />
        </ToastProvider>
      </BrowserRouter>,
    )

    expect(await screen.findByText('Designer Một')).toBeInTheDocument()
    expect(await screen.findByText('Support Một')).toBeInTheDocument()
    expect(screen.getByText('@des_mana_bot')).toBeInTheDocument()
    expect(screen.getAllByText('Đã kết nối')).toHaveLength(2)

    const groupInput = screen.getByPlaceholderText('Ví dụ: -1001234567890')
    fireEvent.change(groupInput, { target: { value: '-1001234567890' } })
    apiFetchMock.mockImplementationOnce(async (path: string) => {
      if (path === '/telegram/admin/designers/designer-1/group') {
        return { ...overview.designers[0], group_chat_id: '-1001234567890', group_configured: true }
      }
      throw new Error(`Unexpected API path: ${path}`)
    })
    fireEvent.click(screen.getByTitle('Lưu group ID'))

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledWith(
      '/telegram/admin/designers/designer-1/group',
      expect.objectContaining({ method: 'PUT', body: JSON.stringify({ group_chat_id: '-1001234567890' }) }),
    ))
  })

  it('renders Telegram HTML in the preview instead of showing raw tags', async () => {
    render(
      <BrowserRouter>
        <ToastProvider>
          <TelegramManagementPage />
        </ToastProvider>
      </BrowserRouter>,
    )

    expect(await screen.findByText('Designer Một')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Xem preview/ }))

    const heading = await screen.findByText('CẢNH BÁO')
    expect(heading.tagName).toBe('STRONG')
    expect(screen.getByText('Ghi chú mẫu').tagName).toBe('EM')
    expect(screen.getByText('DJ0000000').tagName).toBe('CODE')
    expect(screen.queryByText(/<b>|<\/b>|<i>|<\/i>/)).not.toBeInTheDocument()
  })

  it('allows the admin to preview Support duplicate-review messages', async () => {
    render(
      <BrowserRouter>
        <ToastProvider>
          <TelegramManagementPage />
        </ToastProvider>
      </BrowserRouter>,
    )

    expect(await screen.findByText('Support Một')).toBeInTheDocument()
    fireEvent.change(screen.getByDisplayValue('Des — Đơn mới'), {
      target: { value: 'support_duplicate_match_candidate' },
    })
    expect(await screen.findByText('Gửi Support')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Xem preview/ }))

    expect(await screen.findByText('ẢNH ĐÃ CÓ TRONG KHO LỊCH SỬ')).toBeInTheDocument()
  })
})
