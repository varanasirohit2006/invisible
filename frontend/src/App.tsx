import { lazy, Suspense, useEffect, useState, useSyncExternalStore } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, post, remove } from './api'
import type { Dashboard, Page, Source, Workflow } from './types'
import { Pairing } from './components/Pairing'
import { Shell } from './components/Shell'
import { ErrorNotice, Loading } from './components/ui'
import { Overview } from './pages/Overview'

const ActivityPage = lazy(() =>
  import('./pages/Activity').then((module) => ({ default: module.ActivityPage })),
)
const WorkflowsPage = lazy(() =>
  import('./pages/Workflows').then((module) => ({ default: module.WorkflowsPage })),
)
const RunsPage = lazy(() => import('./pages/Runs').then((module) => ({ default: module.RunsPage })))
const SettingsPage = lazy(() =>
  import('./pages/Settings').then((module) => ({ default: module.SettingsPage })),
)
const WorkflowReview = lazy(() =>
  import('./components/WorkflowReview').then((module) => ({ default: module.WorkflowReview })),
)

function subscribeRoute(callback: () => void) {
  window.addEventListener('hashchange', callback)
  return () => window.removeEventListener('hashchange', callback)
}
function currentPage(): Page {
  const value = location.hash.replace('#/', '')
  return ['overview', 'activity', 'workflows', 'runs', 'settings'].includes(value)
    ? (value as Page)
    : 'overview'
}
const navigate = (page: Page) => {
  location.hash = `/${page}`
}

export default function App() {
  const client = useQueryClient()
  const session = useQuery({
    queryKey: ['session'],
    queryFn: () => api<{ connected: boolean }>('/session'),
    retry: false,
    staleTime: Infinity,
  })
  useEffect(() => {
    const disconnect = () => {
      client.setQueryData(['session'], { connected: false })
    }
    window.addEventListener('iwd:disconnected', disconnect)
    return () => window.removeEventListener('iwd:disconnected', disconnect)
  }, [client])
  if (session.isPending)
    return (
      <div className="startup-loading">
        <Loading label="Connecting to your local workspace…" />
      </div>
    )
  if (!session.data?.connected)
    return (
      <Pairing
        onConnect={() => {
          client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'session' })
          client.setQueryData(['session'], { connected: true })
        }}
        connectionError={
          session.error instanceof ApiError && session.error.status !== 401 ? session.error : null
        }
      />
    )
  return <Workspace />
}

function Workspace() {
  const client = useQueryClient()
  const page = useSyncExternalStore(subscribeRoute, currentPage)
  const [source, updateSource] = useState<Source>(() =>
    sessionStorage.getItem('iwd:source') === 'demo' ? 'demo' : 'real',
  )
  const [selected, setSelected] = useState<Workflow | null>(null)
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [page])
  const dashboard = useQuery({
    queryKey: ['dashboard', source],
    queryFn: ({ signal }) => api<Dashboard>(`/dashboard?source=${source}`, { signal }),
    refetchInterval: (query) => {
      const data = query.state.data
      return data?.settings.monitoring_enabled && data.agent.connected && !data.agent.watching
        ? 1000
        : 10000
    },
  })
  const setSource = (value: Source) => {
    updateSource(value)
    sessionStorage.setItem('iwd:source', value)
  }
  const demo = useMutation({
    mutationFn: () => post('/demo'),
    onSuccess: async () => {
      setSource('demo')
      await client.invalidateQueries({ queryKey: ['dashboard'] })
    },
  })
  const disconnect = useMutation({
    mutationFn: () => remove('/session'),
    onSuccess: () => {
      client.setQueryData(['session'], { connected: false })
      client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'session' })
    },
  })
  const data = dashboard.data
  return (
    <Shell
      page={page}
      source={source}
      setSource={setSource}
      agent={data?.agent}
      monitoringEnabled={data?.settings.monitoring_enabled}
      demoAvailable={Boolean(data?.demo_available)}
      onDisconnect={() => disconnect.mutate()}
    >
      <ErrorNotice error={dashboard.error || demo.error || disconnect.error} />
      {data?.agent.error ? (
        <div className="notice notice-warning" role="status">
          Agent needs attention: {data.agent.error}
        </div>
      ) : null}
      {data?.agent.dropped_events ? (
        <div className="notice notice-warning">
          The offline event queue reached its limit. {data.agent.dropped_events} oldest events were
          dropped.
        </div>
      ) : null}
      <Suspense fallback={<Loading />}>
        {page === 'overview' ? (
          data ? (
            <Overview
              data={data}
              onReview={setSelected}
              navigate={navigate}
              onExplore={() => demo.mutate()}
              exploring={demo.isPending}
            />
          ) : dashboard.isPending ? (
            <Loading />
          ) : null
        ) : null}
        {page === 'activity' ? <ActivityPage source={source} key={source} /> : null}
        {page === 'workflows' ? (
          <WorkflowsPage source={source} key={source} onReview={setSelected} navigate={navigate} />
        ) : null}
        {page === 'runs' ? <RunsPage /> : null}
        {page === 'settings' ? <SettingsPage /> : null}
        {selected ? (
          <WorkflowReview
            key={selected.id}
            workflow={selected}
            onClose={() => setSelected(null)}
            navigate={navigate}
            agentConnected={Boolean(data?.agent.connected)}
          />
        ) : null}
      </Suspense>
    </Shell>
  )
}
