import type { ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import ErrorBoundary from '@/components/ErrorBoundary'

/** Resets the error boundary when the user navigates to a different route. */
export default function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  return <ErrorBoundary key={pathname}>{children}</ErrorBoundary>
}
