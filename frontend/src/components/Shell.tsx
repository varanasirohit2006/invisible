import type { ReactNode } from 'react'
import {
  Activity,
  ArrowUpRight,
  CircleHelp,
  History,
  LayoutDashboard,
  LogOut,
  Monitor,
  Settings,
  ShieldCheck,
  Workflow,
} from 'lucide-react'
import type { AgentStatus, Page, Source } from '../types'

const navigation: { page: Page; label: string; icon: typeof Activity }[] = [
  { page: 'overview', label: 'Overview', icon: LayoutDashboard },
  { page: 'activity', label: 'Activity', icon: Activity },
  { page: 'workflows', label: 'Workflows', icon: Workflow },
  { page: 'runs', label: 'Run history', icon: History },
  { page: 'settings', label: 'Settings', icon: Settings },
]

export function Brand() {
  return (
    <div className="brand">
      <span className="brand-mark">
        <Workflow size={25} strokeWidth={1.9} />
      </span>
      <div>
        <span className="brand-name">
          invisible<span className="brand-period">.</span>
        </span>
        <span className="brand-caption">WORK DETECTOR</span>
      </div>
    </div>
  )
}

export function Shell({
  page,
  children,
  agent,
  monitoringEnabled,
  source,
  setSource,
  demoAvailable,
  onDisconnect,
}: {
  page: Page
  children: ReactNode
  agent?: AgentStatus
  monitoringEnabled?: boolean
  source: Source
  setSource: (value: Source) => void
  demoAvailable: boolean
  onDisconnect: () => void
}) {
  const label = agent?.connected
    ? !monitoringEnabled
      ? 'Monitoring paused'
      : agent.error
        ? 'Monitoring needs attention'
        : agent.watching
          ? `Observing ${agent.watching} folder${agent.watching === 1 ? '' : 's'}`
          : 'Monitoring enabled · waiting for folders'
    : 'Agent offline'
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand-link" href="#/overview" aria-label="Invisible Work Detector overview">
          <Brand />
        </a>
        <div className="workspace-label">
          <Monitor size={16} />
          Personal workspace
        </div>
        <nav aria-label="Main navigation">
          {navigation.map(({ page: key, label: text, icon: Icon }) => (
            <a
              key={key}
              href={`#/${key}`}
              className={`nav-item ${page === key ? 'active' : ''}`}
              aria-current={page === key ? 'page' : undefined}
            >
              <Icon size={19} strokeWidth={1.8} />
              <span>{text}</span>
              {page === key ? <span className="nav-active-dot" /> : null}
            </a>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="privacy-note">
            <ShieldCheck size={21} />
            <div>
              <strong>On your device.</strong>
              <p>Your files stay yours.</p>
            </div>
          </div>
          <a href="/api/docs" target="_blank" rel="noreferrer" className="sidebar-help">
            <CircleHelp size={16} />
            <span>Local API documentation</span>
            <ArrowUpRight size={14} />
          </a>
        </div>
      </aside>
      <div className="workspace-main">
        <header className="topbar">
          <div className="breadcrumb">
            <span>Workspace</span>
            <span className="breadcrumb-slash">/</span>
            <strong>{navigation.find((item) => item.page === page)?.label}</strong>
          </div>
          <div className="topbar-tools">
            <span
              className={`agent-indicator ${monitoringEnabled && agent?.connected && agent.watching ? 'is-live' : ''}`}
            >
              <span className="status-dot" />
              {label}
            </span>
            <button
              type="button"
              className="icon-button"
              aria-label="Disconnect dashboard"
              title="Disconnect dashboard"
              onClick={onDisconnect}
            >
              <LogOut size={18} />
            </button>
          </div>
        </header>
        <main id="main-content" className="main-content">
          {['overview', 'activity', 'workflows'].includes(page) &&
          (demoAvailable || source === 'demo') ? (
            <div className={`source-bar ${source === 'demo' ? 'source-bar-demo' : ''}`}>
              <div>
                <span className="source-switch" role="group" aria-label="Activity source">
                  <button
                    type="button"
                    aria-pressed={source === 'real'}
                    onClick={() => setSource('real')}
                  >
                    My activity
                  </button>
                  <button
                    type="button"
                    aria-pressed={source === 'demo'}
                    onClick={() => setSource('demo')}
                  >
                    Sample activity
                  </button>
                </span>
                <span className="source-description">
                  {source === 'demo'
                    ? 'Explore examples. Sample workflows cannot change files.'
                    : 'Your approved local activity.'}
                </span>
              </div>
              {source === 'demo' ? <span className="sample-label">Sample data</span> : null}
            </div>
          ) : null}
          {children}
          <footer className="workspace-footer">
            <span>
              <ShieldCheck size={13} />
              Local by default. Always in your control.
            </span>
            <span>Invisible Work Detector · v0.1</span>
          </footer>
        </main>
      </div>
    </div>
  )
}
