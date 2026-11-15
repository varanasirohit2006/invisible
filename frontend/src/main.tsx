import { Component, StrictMode } from 'react'
import type { ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import { ApiError } from './api'
import './styles.css'

const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5000,
      refetchOnWindowFocus: true,
      retry: (count, error) =>
        count < 1 && !(error instanceof ApiError && [401, 403, 404, 422].includes(error.status)),
    },
  },
})

class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }
  static getDerivedStateFromError() {
    return { failed: true }
  }
  render() {
    return this.state.failed ? (
      <main className="startup-loading">
        <div className="empty-state">
          <h1>The dashboard was interrupted.</h1>
          <p>Your saved data is still on this device. Reload to reconnect.</p>
          <button className="button button-primary" onClick={() => location.reload()}>
            Reload dashboard
          </button>
        </div>
      </main>
    ) : (
      this.props.children
    )
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)
