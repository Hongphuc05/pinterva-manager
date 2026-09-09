import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { AuthProvider } from '../auth/AuthContext'
import { LoginPage } from './LoginPage'

describe('LoginPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.includes('/api/me')) {
          return Promise.resolve({ ok: false, status: 401, statusText: 'Unauthorized' })
        }
        if (url.includes('/api/login')) {
          return Promise.resolve({ ok: true, status: 200, json: async () => ({}) })
        }
        return Promise.reject(new Error(`unexpected fetch: ${url}`))
      })
    )
  })

  it('renders the login form', async () => {
    render(
      <BrowserRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </BrowserRouter>
    )
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Tacahu Ops' })).toBeInTheDocument()
    )
    expect(screen.getByPlaceholderText('Ví dụ: admin hoặc designer1')).toBeInTheDocument()
  })

  it('shows an error on failed login', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes('/api/me')) {
        return Promise.resolve({ ok: false, status: 401, statusText: 'Unauthorized' })
      }
      if (url.includes('/api/login')) {
        return Promise.resolve({
          ok: false,
          status: 401,
          statusText: 'Unauthorized',
          json: async () => ({ detail: 'Invalid credentials' }),
        })
      }
      return Promise.reject(new Error(`unexpected fetch: ${url}`))
    })

    render(
      <BrowserRouter>
        <AuthProvider>
          <LoginPage />
        </AuthProvider>
      </BrowserRouter>
    )
    await waitFor(() => screen.getByPlaceholderText('Ví dụ: admin hoặc designer1'))
    fireEvent.change(screen.getByPlaceholderText('Ví dụ: admin hoặc designer1'), { target: { value: 'x' } })
    fireEvent.change(screen.getByPlaceholderText('••••••••'), { target: { value: 'y' } })
    fireEvent.click(screen.getByRole('button', { name: /Đăng Nhập Hệ Thống/i }))

    await waitFor(() =>
      expect(screen.getByText('Sai tên đăng nhập hoặc mật khẩu')).toBeInTheDocument()
    )
  })
})

