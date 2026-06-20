import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

interface Props {
  children: ReactNode
}

interface State {
  error: Error | null
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Page render error:', error, info.componentStack)
  }

  render() {
    if (this.state.error) {
      return (
        <div className="rounded-xl border border-red-800/50 bg-red-900/20 p-8 max-w-2xl">
          <h1 className="text-xl font-semibold text-red-200">Something went wrong on this page</h1>
          <p className="text-red-300/80 mt-2 text-sm">{this.state.error.message}</p>
          <div className="mt-4 flex gap-3">
            <button
              type="button"
              onClick={() => this.setState({ error: null })}
              className="px-4 py-2 rounded-lg bg-slate-700 text-white text-sm hover:bg-slate-600"
            >
              Try again
            </button>
            <Link to="/" className="px-4 py-2 rounded-lg bg-cyan-600 text-white text-sm hover:bg-cyan-500">
              Back to Dashboard
            </Link>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}
