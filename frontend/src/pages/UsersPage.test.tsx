import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api/client'
import { UsersPage } from './UsersPage'

vi.mock('../components/DashboardLayout', () => ({ DashboardLayout: ({ children }: { children: React.ReactNode }) => <>{children}</> }))
vi.mock('../auth/PlatformContext', () => ({ usePlatform: () => ({ activePlatform: { id: 'plat1', account_username: 'acc@example.com' } }) }))

const api = vi.hoisted(() => ({ apiFetch: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api/client')>()),
  apiFetch: api.apiFetch,
}))

const dan = { id: 'u1', username: 'dan', full_name: 'Dân', role: 'designer', active: true, created_at: '2026-01-01T00:00:00Z' }
const lockedTram = { id: 'u2', username: 'tram', full_name: 'Trâm', role: 'designer', active: false, created_at: '2026-01-02T00:00:00Z' }

function routeFetch(overrides: Record<string, unknown> = {}) {
  api.apiFetch.mockReset().mockImplementation((path: string) => {
    if (path === '/users') return Promise.resolve(overrides.users ?? [dan])
    if (path === '/users?include_locked=true') return Promise.resolve(overrides.usersWithLocked ?? [dan, lockedTram])
    if (path === '/users/unassigned') return Promise.resolve(overrides.unassigned ?? [])
    if (path.startsWith('/users/') && path.endsWith('/active')) return Promise.resolve(overrides.toggleResult ?? { ...dan, active: false })
    if (path.startsWith('/users/')) {
      if (overrides.deleteImpl) return (overrides.deleteImpl as (p: string) => Promise<unknown>)(path)
      return Promise.resolve({ ok: true })
    }
    return Promise.reject(new Error(`unexpected path ${path}`))
  })
}

beforeEach(() => routeFetch())

describe('UsersPage', () => {
  it('hides locked accounts by default and shows them when the checkbox is checked', async () => {
    render(<UsersPage />)
    await waitFor(() => expect(screen.getByText('dan')).toBeInTheDocument())
    expect(screen.queryByText('tram')).not.toBeInTheDocument()
    expect(api.apiFetch).toHaveBeenCalledWith('/users')

    await userEvent.click(screen.getByLabelText('Hiện cả tài khoản đã khóa'))
    await waitFor(() => expect(api.apiFetch).toHaveBeenCalledWith('/users?include_locked=true'))
    await waitFor(() => expect(screen.getByText('tram')).toBeInTheDocument())
  })

  it('locking a user asks to confirm, then calls PATCH active:false', async () => {
    render(<UsersPage />)
    await waitFor(() => expect(screen.getByText('dan')).toBeInTheDocument())
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)

    await userEvent.click(screen.getByTitle('Khóa tài khoản'))

    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('Khóa tài khoản dan?'))
    await waitFor(() => expect(api.apiFetch).toHaveBeenCalledWith('/users/u1/active', {
      method: 'PATCH', body: JSON.stringify({ active: false }),
    }))
    confirmSpy.mockRestore()
  })

  it('declining the lock confirm does not call the API', async () => {
    render(<UsersPage />)
    await waitFor(() => expect(screen.getByText('dan')).toBeInTheDocument())
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    await userEvent.click(screen.getByTitle('Khóa tài khoản'))

    expect(api.apiFetch).not.toHaveBeenCalledWith('/users/u1/active', expect.anything())
  })

  it('unlocking a locked account (shown via the checkbox) needs no confirm', async () => {
    render(<UsersPage />)
    await waitFor(() => expect(screen.getByText('dan')).toBeInTheDocument())
    await userEvent.click(screen.getByLabelText('Hiện cả tài khoản đã khóa'))
    await waitFor(() => expect(screen.getByText('tram')).toBeInTheDocument())
    const confirmSpy = vi.spyOn(window, 'confirm')

    await userEvent.click(screen.getByTitle('Mở khóa tài khoản'))

    expect(confirmSpy).not.toHaveBeenCalled()
    await waitFor(() => expect(api.apiFetch).toHaveBeenCalledWith('/users/u2/active', {
      method: 'PATCH', body: JSON.stringify({ active: true }),
    }))
  })

  it('delete refused (409, has history) offers "Xóa tất cả"; confirming it force-deletes', async () => {
    routeFetch({
      deleteImpl: (path: string) => {
        if (path === '/users/u1') {
          return Promise.reject(new ApiError(409, "'dan' đã có dữ liệu liên quan... Khóa tài khoản..."))
        }
        if (path === '/users/u1?force=true') return Promise.resolve({ ok: true })
        return Promise.reject(new Error(`unexpected ${path}`))
      },
    })
    render(<UsersPage />)
    await waitFor(() => expect(screen.getByText('dan')).toBeInTheDocument())

    await userEvent.click(screen.getByTitle('Xóa tài khoản'))
    await waitFor(() => expect(screen.getByText('Xác Nhận Xóa Tài Khoản')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Xóa'))

    await waitFor(() => expect(screen.getByText(/đã có dữ liệu liên quan/)).toBeInTheDocument())
    const forceButton = screen.getByText('Xóa tất cả')

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    routeFetch({
      deleteImpl: (path: string) => (path === '/users/u1?force=true' ? Promise.resolve({ ok: true }) : Promise.reject(new Error(path))),
      users: [], // after deletion, the list no longer has dan
    })
    await userEvent.click(forceButton)

    expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining('Xóa TẤT CẢ dữ liệu liên quan tới dan?'))
    await waitFor(() => expect(screen.queryByText('Xác Nhận Xóa Tài Khoản')).not.toBeInTheDocument())
    confirmSpy.mockRestore()
  })

  it('a plain delete that succeeds (no history) closes the modal without offering "Xóa tất cả"', async () => {
    render(<UsersPage />)
    await waitFor(() => expect(screen.getByText('dan')).toBeInTheDocument())

    await userEvent.click(screen.getByTitle('Xóa tài khoản'))
    await waitFor(() => expect(screen.getByText('Xác Nhận Xóa Tài Khoản')).toBeInTheDocument())
    await userEvent.click(screen.getByText('Xóa'))

    await waitFor(() => expect(api.apiFetch).toHaveBeenCalledWith('/users/u1', { method: 'DELETE' }))
    await waitFor(() => expect(screen.queryByText('Xác Nhận Xóa Tài Khoản')).not.toBeInTheDocument())
    expect(screen.queryByText('Xóa tất cả')).not.toBeInTheDocument()
  })
})
