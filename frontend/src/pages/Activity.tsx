import { useDeferredValue, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity as ActivityIcon,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Search,
} from 'lucide-react'
import { api } from '../api'
import type { ActivityEvent, Source } from '../types'
import { number } from '../format'
import { ActivityTable } from '../components/ActivityTable'
import { Button, EmptyState, ErrorNotice, Loading, PageHeading } from '../components/ui'

export function ActivityPage({ source }: { source: Source }) {
  const client = useQueryClient()
  const [search, setSearch] = useState('')
  const [kind, setKind] = useState('')
  const [offset, setOffset] = useState(0)
  const query = useDeferredValue(search)
  const events = useQuery({
    queryKey: ['events', source, query, kind, offset],
    queryFn: ({ signal }) =>
      api<{ items: ActivityEvent[]; total: number }>(
        `/events?${new URLSearchParams({ source, q: query, kind, offset: String(offset), limit: '20' })}`,
        { signal },
      ),
    refetchInterval: 10000,
  })
  return (
    <>
      <PageHeading
        title="The little things, made visible."
        description="An exact record of file activity in your approved folders."
        action={
          <Button
            variant="secondary"
            busy={events.isFetching}
            onClick={() => client.invalidateQueries({ queryKey: ['events'] })}
          >
            <RefreshCw size={16} />
            Refresh
          </Button>
        }
      />
      <section className="panel">
        <div className="list-toolbar">
          <div className="search-field">
            <Search size={17} />
            <input
              aria-label="Search activity"
              value={search}
              onChange={(event) => {
                setSearch(event.target.value)
                setOffset(0)
              }}
              placeholder="Search filenames or paths…"
            />
          </div>
          <select
            aria-label="Filter activity type"
            value={kind}
            onChange={(event) => {
              setKind(event.target.value)
              setOffset(0)
            }}
          >
            <option value="">All activity</option>
            <option value="file_created">Created files</option>
            <option value="file_renamed">Renamed files</option>
            <option value="file_moved">Moved files</option>
            <option value="file_modified">Updated files</option>
          </select>
        </div>
        <ErrorNotice error={events.error} />
        {events.isPending ? (
          <Loading label="Loading observed activity…" />
        ) : events.data?.items.length ? (
          <ActivityTable events={events.data.items} />
        ) : (
          <EmptyState
            icon={<ActivityIcon size={26} />}
            title={search || kind ? 'No matching activity' : 'Nothing observed yet'}
            description={
              search || kind
                ? 'Try a different filename or activity type.'
                : 'Approve folders and enable monitoring in Settings to start your activity log.'
            }
          />
        )}
        <div className="pagination">
          <span>
            {number(events.data?.total || 0)} matching actions
            {events.data?.total
              ? ` · ${offset + 1}–${Math.min(offset + 20, events.data.total)}`
              : ''}
          </span>
          <div>
            <Button
              variant="ghost"
              aria-label="Previous activity page"
              disabled={offset === 0 || events.isPending}
              onClick={() => setOffset((value) => Math.max(0, value - 20))}
            >
              <ChevronLeft size={17} />
            </Button>
            <Button
              variant="ghost"
              aria-label="Next activity page"
              disabled={!events.data || offset + 20 >= events.data.total || events.isPending}
              onClick={() => setOffset((value) => value + 20)}
            >
              <ChevronRight size={17} />
            </Button>
          </div>
        </div>
      </section>
      <p className="page-note">
        Only file paths, action types, and timestamps are recorded. File contents are read only when
        you explicitly preview an automation that needs them.
      </p>
    </>
  )
}
