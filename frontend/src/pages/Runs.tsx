import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  History,
  RefreshCw,
} from 'lucide-react'
import { api, post } from '../api'
import type { Run } from '../types'
import { dateTime, duration, runLabels } from '../format'
import { Button, EmptyState, ErrorNotice, Loading, PageHeading } from '../components/ui'

export function RunsPage() {
  const client = useQueryClient()
  const [offset, setOffset] = useState(0)
  const runs = useQuery({
    queryKey: ['runs', offset],
    queryFn: ({ signal }) =>
      api<{ items: Run[]; total: number }>(`/runs?limit=20&offset=${offset}`, { signal }),
    refetchInterval: (query) =>
      query.state.data?.items.some((run) => ['queued', 'running'].includes(run.status))
        ? 1500
        : 10000,
  })
  const cancel = useMutation({
    mutationFn: (id: string) => post(`/runs/${id}/cancel`),
    onSuccess: () => client.invalidateQueries({ queryKey: ['runs'] }),
  })
  return (
    <>
      <PageHeading
        title="Every run. Every result."
        description="Follow the work you approved, from the first step to the last."
        action={
          <Button
            variant="secondary"
            busy={runs.isFetching}
            onClick={() => client.invalidateQueries({ queryKey: ['runs'] })}
          >
            <RefreshCw size={16} />
            Refresh
          </Button>
        }
      />
      <ErrorNotice error={runs.error || cancel.error} />
      <section className="panel run-list">
        {runs.isPending ? (
          <Loading label="Loading run history…" />
        ) : runs.data?.items.length ? (
          runs.data.items.map((run) => (
            <details className="run-row" key={run.id}>
              <summary>
                <span className={`run-icon status-${run.status}`}>
                  {run.status === 'succeeded' ? <CheckCircle2 size={21} /> : <Clock3 size={21} />}
                </span>
                <span className="run-title">
                  <strong>{run.title}</strong>
                  <time dateTime={run.created_at}>{dateTime(run.created_at)}</time>
                </span>
                <span className={`status-badge status-${run.status}`}>{runLabels[run.status]}</span>
                <ChevronDown className="details-chevron" size={18} />
              </summary>
              <div className="run-detail">
                <div className="run-detail-meta">
                  <span>Run {run.id.slice(0, 8)}</span>
                  {run.result?.duration_seconds !== undefined ? (
                    <span>Duration: {duration(run.result.duration_seconds)}</span>
                  ) : null}
                  {run.finished_at ? <span>Finished {dateTime(run.finished_at)}</span> : null}
                </div>
                <ErrorNotice error={run.error} />
                <ol className="run-steps">
                  {run.plan.actions.map((action, index) => {
                    const step = run.result?.steps.find((item) => item.index === index + 1)
                    return (
                      <li key={index}>
                        <span className={`step-number step-${step?.status || 'pending'}`}>
                          {step?.status === 'succeeded' ? <CheckCircle2 size={16} /> : index + 1}
                        </span>
                        <div>
                          <strong>{action.description}</strong>
                          <code>{action.target || action.source}</code>
                          <span className="step-result">
                            {run.status === 'needs_review' && step?.status === 'running'
                              ? 'Unconfirmed — check the files'
                              : step?.status === 'succeeded'
                                ? 'Completed'
                                : step?.status === 'failed'
                                  ? 'Failed'
                                  : step?.status === 'running'
                                    ? 'In progress'
                                    : 'Not started'}
                          </span>
                          {step?.backup ? (
                            <p className="backup-path">
                              Workbook backup: <code>{step.backup}</code>
                            </p>
                          ) : null}
                        </div>
                      </li>
                    )
                  })}
                </ol>
                {run.status === 'queued' ? (
                  <Button
                    variant="secondary"
                    busy={cancel.isPending}
                    onClick={() => cancel.mutate(run.id)}
                  >
                    Cancel queued run
                  </Button>
                ) : null}
              </div>
            </details>
          ))
        ) : (
          <EmptyState
            icon={<History size={28} />}
            title="Your first small win is ahead"
            description="Preview and approve a workflow, then run it. Its progress and results will appear here."
          />
        )}
        <div className="pagination">
          <span>{runs.data?.total || 0} runs · Results are stored on this device</span>
          <div>
            <Button
              variant="ghost"
              aria-label="Previous runs page"
              disabled={offset === 0}
              onClick={() => setOffset((value) => Math.max(0, value - 20))}
            >
              <ChevronLeft size={17} />
            </Button>
            <Button
              variant="ghost"
              aria-label="Next runs page"
              disabled={!runs.data || offset + 20 >= runs.data.total}
              onClick={() => setOffset((value) => value + 20)}
            >
              <ChevronRight size={17} />
            </Button>
          </div>
        </div>
      </section>
    </>
  )
}
