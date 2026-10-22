import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { JobTemplatesCard } from './JobTemplatesCard'

describe('JobTemplatesCard', () => {
  it('shows each template with its image, PSD link and note', () => {
    render(
      <JobTemplatesCard templates={[
        { url: 'https://drive.google.com/drive/folders/aaa', note: 'Folder Mẫu PSD + JPG', image_url: '/api/assets/proxy?u=abc' },
        { url: 'https://drive.google.com/drive/folders/bbb', note: null, image_url: null },
      ]} />,
    )

    expect(screen.getByLabelText('Template của job')).toBeInTheDocument()
    expect(screen.getByText('https://drive.google.com/drive/folders/aaa')).toBeInTheDocument()
    expect(screen.getByText('Folder Mẫu PSD + JPG')).toBeInTheDocument()
    expect(screen.getByAltText('Ảnh template')).toHaveAttribute('src', '/api/assets/proxy?u=abc')
    expect(screen.getAllByText('Link PSD:')).toHaveLength(2)
  })

  it('renders nothing when the job has no template', () => {
    const { container, rerender } = render(<JobTemplatesCard templates={[]} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<JobTemplatesCard templates={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})
