import { ArrowDownToLine, ArrowRight, FilePenLine, FolderInput, PencilLine } from 'lucide-react'
import type { ActivityEvent } from '../types'
import { dateTime, eventLabels, fileName } from '../format'

const icons = {
  file_created: ArrowDownToLine,
  file_renamed: PencilLine,
  file_moved: FolderInput,
  file_modified: FilePenLine,
}

export function ActivityTable({
  events,
  compact = false,
}: {
  events: ActivityEvent[]
  compact?: boolean
}) {
  return (
    <div className="table-scroll">
      <table className={`activity-table ${compact ? 'table-compact' : ''}`}>
        <thead>
          <tr>
            <th>Activity</th>
            <th>File & location</th>
            <th>Observed</th>
          </tr>
        </thead>
        <tbody>
          {events.map((event) => {
            const Icon = icons[event.event_type]
            const path = event.new_path || event.file_path || event.old_path
            return (
              <tr key={event.id}>
                <td>
                  <span className={`event-kind kind-${event.event_type}`}>
                    <Icon size={15} />
                    {eventLabels[event.event_type]}
                  </span>
                </td>
                <td>
                  <div className="file-cell">
                    <strong title={path || ''}>{fileName(path)}</strong>
                    {compact ? (
                      <span title={path || ''}>{path}</span>
                    ) : (
                      <details>
                        <summary>Show observed paths</summary>
                        <div className="observed-paths">
                          {event.old_path ? (
                            <>
                              <code>{event.old_path}</code>
                              <ArrowRight size={13} />
                            </>
                          ) : null}
                          <code>{path}</code>
                        </div>
                      </details>
                    )}
                    <time className="mobile-observed" dateTime={event.timestamp}>
                      Observed {dateTime(event.timestamp)}
                    </time>
                  </div>
                </td>
                <td>
                  <time dateTime={event.timestamp}>{dateTime(event.timestamp)}</time>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
