import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, ScanLine, Search, Sparkles } from 'lucide-react'
import { api, post } from '../api'
import type { Page, Source, Workflow } from '../types'
import { number } from '../format'
import { Button, EmptyState, ErrorNotice, Loading, PageHeading } from '../components/ui'
import { WorkflowHint, WorkflowRow } from '../components/WorkflowRow'

export function WorkflowsPage({
  source,
  onReview,
  navigate,
}: {
  source: Source
  onReview: (workflow: Workflow) => void
  navigate: (page: Page) => void
}) {
  const client = useQueryClient()
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState('impact')
  const workflows = useQuery({
    queryKey: ['workflows', source],
    queryFn: ({ signal }) => api<{ items: Workflow[] }>(`/workflows?source=${source}`, { signal }),
    refetchInterval: 10000,
  })
  const analyze = useMutation({
    mutationFn: () => post('/analyze'),
    onSuccess: async () => {
      await Promise.all([
        client.invalidateQueries({ queryKey: ['workflows'] }),
        client.invalidateQueries({ queryKey: ['dashboard'] }),
      ])
    },
  })
  const filtered = (workflows.data?.items || [])
    .filter((workflow) => workflow.title.toLowerCase().includes(search.toLowerCase()))
    .sort((left, right) =>
      sort === 'frequency'
        ? right.frequency - left.frequency
        : right.potential_seconds - left.potential_seconds,
    )
  return (
    <>
      <PageHeading
        title="Find your next small win."
        description="Recurring file routines, ready for a closer look."
        action={
          <Button busy={analyze.isPending} onClick={() => analyze.mutate()}>
            <ScanLine size={17} />
            Discover patterns
          </Button>
        }
      />
      <ErrorNotice error={analyze.error || workflows.error} />
      {analyze.isSuccess ? (
        <div className="notice notice-success" role="status">
          <Sparkles size={17} />
          Discovery is up to date. Patterns below reflect the current activity log.
        </div>
      ) : null}
      <section className="panel">
        <div className="list-toolbar">
          <div className="search-field">
            <Search size={17} />
            <input
              aria-label="Search workflows"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Find a workflow…"
            />
          </div>
          <select
            aria-label="Sort workflows"
            value={sort}
            onChange={(event) => setSort(event.target.value)}
          >
            <option value="impact">Highest potential savings</option>
            <option value="frequency">Most frequent</option>
          </select>
        </div>
        {workflows.isPending ? (
          <Loading label="Finding your workflows…" />
        ) : filtered.length ? (
          <>
            <div className="list-summary">
              {number(filtered.length)} workflows ·{' '}
              {number(filtered.reduce((count, workflow) => count + workflow.frequency, 0))}{' '}
              recurring sessions
            </div>
            <div className="workflow-list workflow-list-full">
              {filtered.map((workflow) => (
                <WorkflowRow key={workflow.id} workflow={workflow} onReview={onReview} />
              ))}
            </div>
            <WorkflowHint />
          </>
        ) : (
          <EmptyState
            icon={<Sparkles size={27} />}
            title={search ? 'No matching workflows' : 'A little observation goes a long way'}
            description={
              search
                ? 'Try a different search.'
                : 'Once a routine repeats in separate sessions, it will appear here. Enable monitoring and go about your usual work.'
            }
            action={
              !search ? (
                <Button variant="secondary" onClick={() => navigate('settings')}>
                  Manage approved folders
                  <ArrowRight size={15} />
                </Button>
              ) : undefined
            }
          />
        )}
      </section>
      <div className="how-it-works">
        <div>
          <span>01</span>
          <h3>Observe a pattern</h3>
          <p>Repeated sequences are grouped without using filenames as model inputs.</p>
        </div>
        <div>
          <span>02</span>
          <h3>Make it your own</h3>
          <p>Choose files, naming rules, and destinations. Preview the exact changes.</p>
        </div>
        <div>
          <span>03</span>
          <h3>Approve one run</h3>
          <p>Nothing changes until you approve and explicitly run the automation.</p>
        </div>
      </div>
    </>
  )
}
