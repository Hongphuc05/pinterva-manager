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
      expect(screen.getByRole('heading', { name: 'Đăng nhập' })).toBeInTheDocument()
    )
    expect(screen.getByPlaceholderText('Tên đăng nhập')).toBeInTheDocument()
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
    await waitFor(() => screen.getByPlaceholderText('Tên đăng nhập'))
    fireEvent.change(screen.getByPlaceholderText('Tên đăng nhập'), { target: { value: 'x' } })
    fireEvent.change(screen.getByPlaceholderText('Mật khẩu'), { target: { value: 'y' } })
    fireEvent.click(screen.getByRole('button', { name: 'Đăng nhập' }))

    await waitFor(() =>
      expect(screen.getByText('Sai tên đăng nhập hoặc mật khẩu')).toBeInTheDocument()
    )
  })
})
