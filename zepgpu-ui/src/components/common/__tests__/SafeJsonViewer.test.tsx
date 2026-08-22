import { fireEvent, render, screen } from '@testing-library/react'
import SafeJsonViewer from '@/components/common/SafeJsonViewer'

describe('SafeJsonViewer', () => {
  it('renders small JSON normally', () => {
    render(
      <SafeJsonViewer
        value={{ status: 'ok' }}
        maxInlineChars={100}
      />,
    )

    expect(screen.getByText(/"status": "ok"/)).toBeInTheDocument()
    expect(screen.queryByText(/truncated/)).not.toBeInTheDocument()
  })

  it('truncates JSON larger than the inline limit', () => {
    render(
      <SafeJsonViewer
        value={{ payload: 'x'.repeat(500) }}
        maxInlineChars={50}
      />,
    )

    expect(screen.getByText(/truncated/)).toBeInTheDocument()
    expect(screen.getByText('Show full JSON')).toBeInTheDocument()
  })

  it('allows moderately large JSON to be expanded', () => {
    render(
      <SafeJsonViewer
        value={{ payload: 'x'.repeat(500) }}
        maxInlineChars={50}
        hardRenderLimit={1000}
      />,
    )

    fireEvent.click(screen.getByText('Show full JSON'))

    expect(screen.getByText('Show truncated')).toBeInTheDocument()
  })

  it('does not allow extremely large JSON to be fully rendered', () => {
    render(
      <SafeJsonViewer
        value={{ payload: 'x'.repeat(5000) }}
        maxInlineChars={50}
        hardRenderLimit={100}
      />,
    )

    expect(screen.getByText('Too large to render fully')).toBeInTheDocument()
    expect(screen.queryByText('Show full JSON')).not.toBeInTheDocument()
  })
})