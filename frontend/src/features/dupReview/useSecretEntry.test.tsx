import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSecretEntry } from './useSecretEntry'

const auth = vi.hoisted(() => ({ role: 'support' as string | null }))
vi.mock('../../auth/AuthContext', () => ({ useAuth: () => ({ user: auth.role ? { role: auth.role } : null }) }))

function Home() {
  const { onLogoClick } = useSecretEntry()
  return (
    <div>
      <button onClick={onLogoClick}>logo</button>
      <input aria-label="ô nhập" />
    </div>
  )
}

const renderApp = () =>
  render(
    <MemoryRouter initialEntries={['/orders']}>
      <Routes>
        <Route path="/orders" element={<Home />} />
        <Route path="/duplicate-review" element={<p>khu vực ẩn</p>} />
      </Routes>
    </MemoryRouter>,
  )

const shortcut = (init: KeyboardEventInit = {}) => fireEvent.keyDown(window, { code: 'KeyD', altKey: true, shiftKey: true, ...init })

beforeEach(() => {
  auth.role = 'support'
  vi.useRealTimers()
})

describe('secret entry to the review area', () => {
  it('Alt+Shift+D opens it for Support', () => {
    renderApp()
    shortcut()
    expect(screen.getByText('khu vực ẩn')).toBeInTheDocument()
  })

  it('other key combinations and typing in a field do nothing', () => {
    renderApp()
    shortcut({ altKey: false })
    shortcut({ shiftKey: false })
    shortcut({ ctrlKey: true })
    fireEvent.keyDown(screen.getByLabelText('ô nhập'), { code: 'KeyD', altKey: true, shiftKey: true })
    expect(screen.queryByText('khu vực ẩn')).not.toBeInTheDocument()
  })

  it('five quick clicks on the logo open it; fewer do not', () => {
    renderApp()
    for (let i = 0; i < 4; i++) fireEvent.click(screen.getByText('logo'))
    expect(screen.queryByText('khu vực ẩn')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('logo'))
    expect(screen.getByText('khu vực ẩn')).toBeInTheDocument()
  })

  it('slow clicks do not add up', () => {
    vi.useFakeTimers()
    renderApp()
    for (let i = 0; i < 5; i++) {
      fireEvent.click(screen.getByText('logo'))
      vi.advanceTimersByTime(2000)
    }
    expect(screen.queryByText('khu vực ẩn')).not.toBeInTheDocument()
  })

  it('does nothing for other roles', () => {
    auth.role = 'admin'
    renderApp()
    shortcut()
    for (let i = 0; i < 5; i++) fireEvent.click(screen.getByText('logo'))
    expect(screen.queryByText('khu vực ẩn')).not.toBeInTheDocument()
  })
})
