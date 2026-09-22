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
  designer_count: 1,
  private_connected_count: 1,
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
}]

describe('TelegramManagementPage', () => {
  beforeEach(() => {
    apiFetchMock.mockImplementation(async (path: string) => {
      if (path === '/telegram/admin/overview') return overview
      if (path === '/telegram/admin/templates') return templates
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
    expect(screen.getByText('@des_mana_bot')).toBeInTheDocument()
    expect(screen.getByText('Đã kết nối')).toBeInTheDocument()

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
})
