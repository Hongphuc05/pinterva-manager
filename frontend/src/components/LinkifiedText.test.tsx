import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { LinkifiedText } from './LinkifiedText'

describe('LinkifiedText', () => {
  it('shows image-proxy paths of a Fix note as numbered image links, and full links as they are', () => {
    render(<LinkifiedText text={'fix visor : https://prnt.sc/iXGCwFr8zGq6\nẢnh: /api/assets/proxy?u=aHR0cHM6Ly9h\nẢnh: /api/assets/proxy?u=aHR0cHM6Ly9i'} />)

    expect(screen.getByRole('link', { name: 'https://prnt.sc/iXGCwFr8zGq6' })).toHaveAttribute('href', 'https://prnt.sc/iXGCwFr8zGq6')
    expect(screen.getByRole('link', { name: 'Ảnh 1' })).toHaveAttribute('href', '/api/assets/proxy?u=aHR0cHM6Ly9h')
    expect(screen.getByRole('link', { name: 'Ảnh 2' })).toHaveAttribute('href', '/api/assets/proxy?u=aHR0cHM6Ly9i')
    expect(screen.queryByText(/proxy\?u=/)).not.toBeInTheDocument()
  })
})
