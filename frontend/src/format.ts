export const number = (value: number) => new Intl.NumberFormat().format(value)

export function duration(seconds: number) {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

export const fileName = (path: string | null) => path?.split(/[\\/]/).at(-1) || 'File'
export const parentFolder = (path: string | null) => path?.replace(/[\\/][^\\/]+$/, '') || ''

export function dateTime(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(value))
}

export const eventLabels: Record<string, string> = {
  file_created: 'Created',
  file_renamed: 'Renamed',
  file_moved: 'Moved',
  file_modified: 'Updated',
}
export const runLabels: Record<string, string> = {
  queued: 'Queued',
  running: 'Running',
  succeeded: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  needs_review: 'Needs review',
}
