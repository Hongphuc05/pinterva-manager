import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({ apiFetch: vi.fn(), apiFetchBlob: vi.fn() }))
vi.mock('../api/client', () => api)

import { MockupPicker } from './MockupImages'

const img = (id: string) => ({ id, filename: `${id}.png`, width: 10, height: 10, submitted_at: null, on_printerval: false,
  url: `/api/orders/o1/result-images/${id}/file` })
const png = (name: string) => new File(['png'], name, { type: 'image/png' })

describe('MockupPicker', () => {
  beforeEach(() => {
    api.apiFetch.mockReset()
    api.apiFetchBlob.mockReset().mockReturnValue(new Promise(() => {}))
  })

  it('uploads chosen images and reports their ids, and removing one reports the rest', async () => {
    const onChange = vi.fn()
    api.apiFetch
      .mockResolvedValueOnce({ staged: [] })
      .mockResolvedValueOnce({ staged: [img('a'), img('b')] })
      .mockResolvedValueOnce({ staged: [img('b')] })
    render(<MockupPicker orderId="o1" onChange={onChange} />)
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith([]))

    fireEvent.change(screen.getByLabelText('Chọn ảnh mockup'), { target: { files: [png('a.png'), png('b.png')] } })
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(['a', 'b']))
    const [, init] = api.apiFetch.mock.calls[1]
    expect(init.method).toBe('POST')
    expect((init.body as FormData).getAll('images')).toHaveLength(2)

    fireEvent.click(screen.getByRole('button', { name: 'Bỏ ảnh a.png' }))
    await waitFor(() => expect(onChange).toHaveBeenLastCalledWith(['b']))
  })

  it('refuses other formats and anything beyond three images', async () => {
    api.apiFetch.mockResolvedValueOnce({ staged: [img('a'), img('b')] }).mockResolvedValueOnce({ staged: [img('a'), img('b'), img('c')] })
    render(<MockupPicker orderId="o1" onChange={vi.fn()} />)
    await screen.findByRole('button', { name: 'Bỏ ảnh b.png' })

    fireEvent.change(screen.getByLabelText('Chọn ảnh mockup'), {
      target: { files: [new File(['gif'], 'x.gif', { type: 'image/gif' }), png('c.png'), png('d.png')] },
    })
    expect(await screen.findByText('Tối đa 3 ảnh mockup.')).toBeInTheDocument()
    const [, init] = api.apiFetch.mock.calls[1]
    expect((init.body as FormData).getAll('images').map((f) => (f as File).name)).toEqual(['c.png'])
    await waitFor(() => expect(screen.queryByText(/Ảnh mockup \(/)).not.toBeInTheDocument()) // 3/3: no add button
  })
})
