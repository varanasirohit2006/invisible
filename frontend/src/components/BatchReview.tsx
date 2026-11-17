import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, CheckCircle2, Layers, Play, RefreshCw, ShieldCheck } from 'lucide-react'
import { post } from '../api'
import type { BatchItem, BatchRunResult, Page, Preview } from '../types'
import { fileName } from '../format'
import { Button, Dialog, ErrorNotice, Field, Loading } from './ui'

interface Row extends BatchItem {
  key: string
  included: boolean
  dirty: boolean
}

export function BatchReview({
  onClose,
  navigate,
  agentConnected,
}: {
  onClose: () => void
  navigate: (page: Page) => void
  agentConnected: boolean
}) {
  const client = useQueryClient()
  const simulate = useQuery({
    queryKey: ['batch-simulate'],
    queryFn: () => post<{ items: BatchItem[] }>('/batch/simulate'),
    retry: false,
    staleTime: 0,
    refetchOnWindowFocus: false,
  })
  const [rows, setRows] = useState<Row[]>([])
  const [result, setResult] = useState<BatchRunResult | null>(null)
  useEffect(() => {
    if (simulate.data) {
      setRows(
        simulate.data.items.map((item, index) => ({
          ...item,
          key: `${item.source_file}-${index}`,
          included: true,
          dirty: false,
        })),
      )
    }
  }, [simulate.data])

  function editRow(key: string, patch: Partial<Row>) {
    setRows((old) => old.map((row) => (row.key === key ? { ...row, ...patch, dirty: true } : row)))
  }
  function toggle(key: string) {
    setRows((old) =>
      old.map((row) => (row.key === key ? { ...row, included: !row.included } : row)),
    )
  }

  const included = rows.filter((row) => row.included)
  const missing = included.filter((row) => !row.destination_folder.trim())
  const canRun = included.length > 0 && missing.length === 0 && agentConnected

  const run = useMutation({
    mutationFn: async () => {
      const items: { workflow_id: number; preview_id: string }[] = []
      for (const row of included) {
        let previewId = row.preview_id
        if (!previewId || row.dirty) {
          const preview = await post<Preview>('/preview', {
            workflow_id: row.workflow_id,
            params: {
              source_file: row.source_file,
              new_name: row.new_name || fileName(row.source_file),
              destination_folder: row.destination_folder,
              extract_invoice: false,
              tracker_file: '',
              tracker_sheet: 'Invoices',
              invoice_number: '',
              invoice_date: '',
              invoice_amount: '',
            },
          })
          previewId = preview.id
        }
        items.push({ workflow_id: row.workflow_id, preview_id: previewId })
      }
      return post<BatchRunResult>('/batch/run', { items })
    },
    onSuccess: async (value) => {
      setResult(value)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['runs'] }),
        client.invalidateQueries({ queryKey: ['dashboard'] }),
        client.invalidateQueries({ queryKey: ['workflows'] }),
      ])
    },
  })

  function go(page: Page) {
    onClose()
    navigate(page)
  }

  return (
    <Dialog title="File everything at once" onClose={onClose} wide>
      {result ? (
        <>
          <div className="dialog-body run-success">
            <div className="success-symbol">
              <CheckCircle2 size={36} />
            </div>
            <h2>Your batch is queued.</h2>
            <p>
              {result.count} approved {result.count === 1 ? 'file' : 'files'} will be filed one
              after another by the local agent. Follow each result in run history.
            </p>
          </div>
          <div className="dialog-footer">
            <Button onClick={() => go('runs')}>
              View run history
              <ArrowRight size={16} />
            </Button>
          </div>
        </>
      ) : (
        <>
          <div className="dialog-body review-body">
            <div className="review-title">
              <div className="workflow-icon">
                <Layers size={24} />
              </div>
              <div>
                <h3>Batch filing</h3>
                <p>
                  Every pending file the app recognizes, with destinations learned from your
                  previous moves. Nothing changes until you approve and run.
                </p>
              </div>
            </div>
            {simulate.isPending ? (
              <Loading label="Gathering your pending files…" />
            ) : simulate.error ? (
              <ErrorNotice error={simulate.error} />
            ) : rows.length === 0 ? (
              <div className="notice">
                Nothing to file right now. Once a routine repeats and new matching files appear in
                your approved folders, they will show up here.
              </div>
            ) : (
              <>
                <div className="batch-summary">
                  <span>
                    {included.length} of {rows.length} selected
                    {missing.length ? ` · ${missing.length} still need a folder` : ''}
                  </span>
                  <Button
                    variant="ghost"
                    busy={simulate.isFetching}
                    onClick={() => simulate.refetch()}
                  >
                    <RefreshCw size={14} />
                    Start over
                  </Button>
                </div>
                <div className="batch-list">
                  {rows.map((row) => {
                    const target = row.plan?.actions.find((action) => action.target)?.target
                    return (
                      <div
                        className={row.included ? 'batch-row' : 'batch-row batch-row-skipped'}
                        key={row.key}
                      >
                        <div className="batch-row-head">
                          <label className="batch-check">
                            <input
                              type="checkbox"
                              aria-label={`Include ${fileName(row.source_file)}`}
                              checked={row.included}
                              onChange={() => toggle(row.key)}
                            />
                          </label>
                          <div className="batch-name">
                            <strong>{fileName(row.source_file)}</strong>
                            <small>{row.workflow_title}</small>
                          </div>
                          <span className="status-badge">
                            {!row.included
                              ? 'Skipped'
                              : !row.destination_folder.trim()
                                ? 'Needs a folder'
                                : row.dirty || !row.preview_id
                                  ? 'Will preview'
                                  : 'Ready'}
                          </span>
                        </div>
                        <code className="batch-source">{row.source_file}</code>
                        <div className="batch-fields">
                          <Field
                            label="Destination folder"
                            placeholder="Full path to an approved folder"
                            value={row.destination_folder}
                            onChange={(event) =>
                              editRow(row.key, { destination_folder: event.target.value })
                            }
                            spellCheck={false}
                          />
                          <Field
                            label="New filename"
                            value={row.new_name}
                            onChange={(event) => editRow(row.key, { new_name: event.target.value })}
                            spellCheck={false}
                          />
                        </div>
                        {row.candidates.length ? (
                          <div className="destination-candidates">
                            {row.candidates.slice(0, 4).map((candidate) => (
                              <Button
                                key={candidate.folder}
                                type="button"
                                variant="secondary"
                                onClick={() =>
                                  editRow(row.key, { destination_folder: candidate.folder })
                                }
                              >
                                Use {fileName(candidate.folder)}
                              </Button>
                            ))}
                          </div>
                        ) : null}
                        <p className="field-hint">{row.reason}</p>
                        {target ? (
                          <p className="batch-target">
                            <ArrowRight size={14} />
                            <code>{target}</code>
                          </p>
                        ) : null}
                      </div>
                    )
                  })}
                </div>
                <ErrorNotice error={run.error} />
                {missing.length ? (
                  <div className="notice notice-warning">
                    Choose a folder for every selected file, or untick the ones you want to skip.
                  </div>
                ) : null}
                {!agentConnected ? (
                  <div className="notice">Your agent is offline. Start it before running.</div>
                ) : null}
              </>
            )}
          </div>
          <div className="dialog-footer">
            <span className="footer-privacy">
              <ShieldCheck size={15} />
              Your files stay on this device
            </span>
            <Button busy={run.isPending} disabled={!canRun} onClick={() => run.mutate()}>
              <Play size={16} />
              Approve &amp; run all{included.length ? ` (${included.length})` : ''}
            </Button>
          </div>
        </>
      )}
    </Dialog>
  )
}
