import {
  Activity,
  ArrowRight,
  CheckCheck,
  Clock3,
  FolderPlus,
  Lightbulb,
  ShieldCheck,
  Sparkles,
  Workflow as WorkflowIcon,
} from 'lucide-react'
import type { Dashboard, Page, Workflow } from '../types'
import { duration, number } from '../format'
import { ActivityTable } from '../components/ActivityTable'
import { Button, EmptyState, PageHeading, TextLink } from '../components/ui'
import { WorkflowHint, WorkflowRow } from '../components/WorkflowRow'

function ActivityChart({ days }: { days: Dashboard['activity'] }) {
  const max = Math.max(4, ...days.map((day) => day.count))
  const ceiling = Math.ceil(max / 4) * 4
  return (
    <div className="activity-chart">
      <svg
        viewBox="0 0 650 190"
        role="img"
        aria-label={`Actions observed by UTC day: ${days.map((day) => `${day.date}: ${day.count}`).join('; ')}`}
      >
        {[0, 1, 2, 3, 4].map((index) => (
          <g key={index}>
            <line
              x1="34"
              y1={155 - index * 33}
              x2="641"
              y2={155 - index * 33}
              stroke="#e7ece9"
              strokeDasharray={index ? '3 5' : undefined}
            />
            <text x="22" y={159 - index * 33} textAnchor="end" className="chart-label">
              {(ceiling / 4) * index}
            </text>
          </g>
        ))}
        {days.map((day, index) => {
          const height = (day.count / ceiling) * 132
          return (
            <g key={day.date}>
              <rect
                x={58 + index * 85}
                y={155 - Math.max(day.count ? 4 : 0, height)}
                width="37"
                height={Math.max(day.count ? 4 : 0, height)}
                rx="5"
                fill={index === 6 ? '#24634b' : '#b7d2c1'}
              />
              <text x={76 + index * 85} y="182" textAnchor="middle" className="chart-label">
                {new Date(`${day.date}T12:00:00Z`).toLocaleDateString(undefined, {
                  weekday: 'short',
                  timeZone: 'UTC',
                })}
              </text>
              {day.count > 0 ? (
                <text
                  x={76 + index * 85}
                  y={Math.max(16, 145 - height)}
                  textAnchor="middle"
                  className="chart-value"
                >
                  {day.count}
                </text>
              ) : null}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

export function Overview({
  data,
  onReview,
  navigate,
  onExplore,
  exploring,
}: {
  data: Dashboard
  onReview: (workflow: Workflow) => void
  navigate: (page: Page) => void
  onExplore: () => void
  exploring: boolean
}) {
  const stats = [
    {
      label: 'Observed actions',
      value: number(data.stats.observed_events),
      detail: `Within ${data.settings.retention_days}-day retention`,
      icon: Activity,
    },
    {
      label: 'Recurring workflows',
      value: number(data.stats.workflow_count),
      detail: 'Patterns worth a closer look',
      icon: WorkflowIcon,
    },
    {
      label: 'Potential time saved',
      value: duration(data.stats.potential_seconds),
      detail: 'Estimated across observed sessions',
      icon: Clock3,
    },
    {
      label: 'Completed runs',
      value: number(data.stats.successful_runs),
      detail: 'Automations you approved',
      icon: CheckCheck,
    },
  ]
  const observing =
    data.settings.monitoring_enabled && data.agent.connected && data.agent.watching > 0
  return (
    <>
      <PageHeading
        title="A clearer picture of your work."
        description="Spot the repetition. Make space for what matters."
        action={
          <Button variant="secondary" onClick={() => navigate('settings')}>
            <FolderPlus size={16} />
            Manage folders
          </Button>
        }
      />
      <div className="metrics-band">
        {stats.map(({ label, value, detail, icon: Icon }, index) => (
          <div className={`metric ${index === 2 ? 'metric-highlight' : ''}`} key={label}>
            <div className="metric-label">
              <span>{label}</span>
              <Icon size={17} strokeWidth={1.7} />
            </div>
            <strong className="metric-value">{value}</strong>
            <span className="metric-description">{detail}</span>
          </div>
        ))}
      </div>
      <div className="overview-middle">
        <section className="panel chart-panel">
          <div className="panel-heading">
            <div>
              <h2>Your activity, at a glance</h2>
              <p>Small actions add up.</p>
            </div>
            <span className="period-label">Last 7 days · UTC</span>
          </div>
          <ActivityChart days={data.activity} />
          <div className="chart-caption">
            <span className="legend-dot" />
            Approved file activity
            <span>
              {number(data.activity.reduce((sum, day) => sum + day.count, 0))} actions this week
            </span>
          </div>
        </section>
        <section className="insight-panel">
          <div className="insight-symbol">
            <Lightbulb size={25} strokeWidth={1.5} />
          </div>
          <h2>
            {data.stats.workflow_count
              ? 'Your next hour back starts here.'
              : 'Start with one folder.'}
          </h2>
          <p>
            {data.stats.workflow_count
              ? 'A few small routines can take up a surprising part of your day. Review a pattern and decide what to automate.'
              : 'Choose a folder where repetitive work happens. We’ll look for patterns in file creates, renames, moves, and updates.'}
          </p>
          <button
            type="button"
            className="insight-link"
            onClick={() => navigate(data.stats.workflow_count ? 'workflows' : 'settings')}
          >
            {data.stats.workflow_count ? 'Explore your workflows' : 'Choose approved folders'}
            <ArrowRight size={17} />
          </button>
          <div className="insight-bottom">
            <ShieldCheck size={15} />
            <span>Every automation needs your approval.</span>
          </div>
        </section>
      </div>
      <section className="panel workflows-panel">
        <div className="panel-heading">
          <div className="heading-with-count">
            <h2>Opportunities to simplify</h2>
            <span className="count-label">{data.stats.workflow_count}</span>
          </div>
          <TextLink onClick={() => navigate('workflows')}>View workflows</TextLink>
        </div>
        {data.workflows.length ? (
          <>
            <div className="workflow-list">
              {data.workflows.slice(0, 3).map((workflow) => (
                <WorkflowRow key={workflow.id} workflow={workflow} onReview={onReview} />
              ))}
            </div>
            <WorkflowHint />
          </>
        ) : (
          <EmptyState
            icon={<Sparkles size={25} />}
            title="The patterns will come into focus"
            description={`Repeat a file workflow in approved folders at least ${data.settings.minimum_support} times. Discovery checks your activity automatically.`}
            action={
              <Button variant="secondary" busy={exploring} onClick={onExplore}>
                Explore sample activity
                <ArrowRight size={15} />
              </Button>
            }
          />
        )}
      </section>
      <div className="overview-bottom">
        <section className="panel recent-panel">
          <div className="panel-heading">
            <h2>Recently observed</h2>
            <TextLink onClick={() => navigate('activity')}>View all activity</TextLink>
          </div>
          {data.recent_events.length ? (
            <ActivityTable events={data.recent_events.slice(0, 4)} compact />
          ) : (
            <div className="quiet-empty">
              <Activity size={20} />
              <p>Your approved file activity will appear here.</p>
            </div>
          )}
        </section>
        <section className="panel monitor-panel">
          <div className="panel-heading">
            <h2>Your local agent</h2>
            <span className={`status-dot ${observing ? 'dot-live' : ''}`} />
          </div>
          <div className="monitor-main">
            <span className="monitor-icon">
              <ShieldCheck size={29} strokeWidth={1.4} />
            </span>
            <h3>
              {!data.agent.connected
                ? 'Ready when you are'
                : observing
                  ? 'Observing approved folders'
                  : !data.settings.monitoring_enabled
                    ? 'Connected. Monitoring paused.'
                    : data.agent.error
                      ? 'Monitoring needs attention'
                      : 'Monitoring enabled. Waiting for folders.'}
            </h3>
            <p>
              {observing
                ? `${data.agent.watching} approved folder${data.agent.watching === 1 ? '' : 's'}. File activity only. No keystrokes or screen recording.`
                : data.settings.monitoring_enabled
                  ? 'Monitoring is enabled. Check that your approved folders are available and the local agent is running.'
                  : 'You choose what to observe and when. Add folders or resume monitoring in Settings.'}
            </p>
          </div>
          <TextLink onClick={() => navigate('settings')}>Manage permissions</TextLink>
        </section>
      </div>
    </>
  )
}
