import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Clock3,
  FileCheck2,
  Play,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import { api, post } from '../api'
import type {
  AutomationParams,
  DestinationSuggestion,
  Page,
  Preview,
  Suggestion,
  Workflow,
} from '../types'
import { dateTime, duration, fileName } from '../format'
import { Button, Dialog, ErrorNotice, Field, Loading } from './ui'

const actionLabels: Record<string, string> = {
  extract_pdf: 'Read invoice fields',
  rename: 'Rename file',
  move: 'Move file',
  append_excel: 'Update Excel tracker',
}

export function WorkflowReview({
  workflow,
  onClose,
  navigate,
  agentConnected,
}: {
  workflow: Workflow
  onClose: () => void
  navigate: (page: Page) => void
  agentConnected: boolean
}) {
  const client = useQueryClient()
  const invoice =
    workflow.sequence.includes('file_modified:xlsx') &&
    workflow.sequence.some((step) => step.endsWith(':pdf'))
  const includesMove = workflow.sequence.some((step) => step.startsWith('file_moved:'))
  const [params, setParams] = useState<AutomationParams>({
    source_file: '',
    new_name: invoice ? 'Invoice_{invoice_number}.pdf' : '',
    destination_folder: '',
    extract_invoice: invoice,
    tracker_file: workflow.is_demo ? '' : workflow.sample_paths.tracker || '',
    tracker_sheet: 'Invoices',
    invoice_number: '',
    invoice_date: '',
    invoice_amount: '',
  })
  const [preview, setPreview] = useState<Preview | null>(null)
  const [approval, setApproval] = useState<string | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [expired, setExpired] = useState(false)
  const [destinationMode, setDestinationMode] = useState<'auto' | 'manual' | 'keep'>(
    includesMove ? 'auto' : 'keep',
  )
  const [confirmedSource, setConfirmedSource] = useState<string | null>(null)
  const [lookupSource, setLookupSource] = useState('')
  const source = params.source_file.trim()
  const destinationConfirmed =
    confirmedSource === source && Boolean(params.destination_folder.trim())
  const destinationReady = destinationMode === 'keep' || destinationConfirmed
  useEffect(() => {
    const timer = window.setTimeout(() => setLookupSource(source), 400)
    return () => window.clearTimeout(timer)
  }, [source])
  const destination = useQuery({
    queryKey: ['destination', workflow.id, lookupSource],
    queryFn: ({ signal }) =>
      api<DestinationSuggestion>('/destination', {
        method: 'POST',
        body: JSON.stringify({ workflow_id: workflow.id, source_file: lookupSource }),
        signal,
      }),
    enabled:
      Boolean(lookupSource) &&
      lookupSource === source &&
      destinationMode === 'auto' &&
      !workflow.is_demo &&
      !preview,
    retry: false,
    staleTime: 0,
  })
  const destinationData = lookupSource === source ? destination.data : undefined
  const proposedFolder = destinationConfirmed
    ? params.destination_folder
    : destinationData?.destination_folder
  const suggestion = useQuery({
    queryKey: ['suggestion', workflow.id],
    queryFn: () => post<Suggestion>('/suggest', { workflow_id: workflow.id }),
    staleTime: Infinity,
    retry: false,
  })
  const prepare = useMutation({
    mutationFn: () => post<Preview>('/preview', { workflow_id: workflow.id, params }),
    onSuccess: (value) => {
      setPreview(value)
      setApproval(null)
    },
  })
  const approve = useMutation({
    mutationFn: () =>
      post<{ id: string }>('/approve', { workflow_id: workflow.id, preview_id: preview?.id }),
    onSuccess: (value) => setApproval(value.id),
  })
  const execute = useMutation({
    mutationFn: () =>
      post<{ id: string }>('/execute', { workflow_id: workflow.id, approval_id: approval }),
    onSuccess: async (value) => {
      setRunId(value.id)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['runs'] }),
        client.invalidateQueries({ queryKey: ['dashboard'] }),
        client.invalidateQueries({ queryKey: ['workflows'] }),
      ])
    },
  })
  useEffect(() => {
    setExpired(false)
    if (!preview) return
    const timer = window.setTimeout(
      () => setExpired(true),
      Math.max(0, new Date(preview.expires_at).getTime() - Date.now()),
    )
    return () => window.clearTimeout(timer)
  }, [preview])
  function change<K extends keyof AutomationParams>(key: K, value: AutomationParams[K]) {
    setParams((old) => ({
      ...old,
      [key]: value,
      ...(key === 'source_file' ? { destination_folder: '' } : {}),
    }))
    if (key === 'source_file') {
      setConfirmedSource(null)
      setDestinationMode(includesMove ? 'auto' : 'keep')
    } else if (key === 'destination_folder') {
      setConfirmedSource(null)
    }
  }
  function confirmDestination(folder: string) {
    setParams((old) => ({ ...old, destination_folder: folder.trim() }))
    setConfirmedSource(source)
  }
  function editDestination() {
    setParams((old) => ({ ...old, destination_folder: proposedFolder || old.destination_folder }))
    setConfirmedSource(null)
    setDestinationMode('manual')
  }
  function keepDestination() {
    setParams((old) => ({ ...old, destination_folder: '' }))
    setConfirmedSource(null)
    setDestinationMode('keep')
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    if (!destinationReady) return
    prepare.mutate()
  }
  function edit() {
    setPreview(null)
    setApproval(null)
    prepare.reset()
    approve.reset()
    execute.reset()
  }
  function go(page: Page) {
    onClose()
    navigate(page)
  }

  return (
    <Dialog title="Review workflow" onClose={onClose} wide>
      {runId ? (
        <>
          <div className="dialog-body run-success">
            <div className="success-symbol">
              <CheckCircle2 size={36} />
            </div>
            <h2>Your automation is queued.</h2>
            <p>
              The local agent will run your approved plan. Follow every step and its result in run
              history.
            </p>
            <code>Run {runId.slice(0, 8)}</code>
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
                <Sparkles size={24} />
              </div>
              <div>
                <h3>{workflow.title}</h3>
                <p>
                  {workflow.frequency} occurrences<span>·</span>
                  <Clock3 size={13} />
                  {duration(workflow.potential_seconds)} potential savings
                </p>
              </div>
            </div>
            {suggestion.isPending ? (
              <Loading label="Preparing a workflow explanation…" />
            ) : suggestion.data ? (
              <div className="recommendation">
                <div className="recommendation-heading">
                  <Sparkles size={15} />
                  <strong>
                    {suggestion.data.provider === 'openai'
                      ? 'AI recommendation'
                      : 'Local recommendation'}
                  </strong>
                  {workflow.is_demo ? <span className="small-tag">Sample</span> : null}
                </div>
                <p>{suggestion.data.summary}</p>
                {!preview ? (
                  <ol>
                    {suggestion.data.steps.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ol>
                ) : null}
                {suggestion.data.notice ? (
                  <p className="provider-note">{suggestion.data.notice}</p>
                ) : null}
              </div>
            ) : null}
            <ErrorNotice error={suggestion.error} />
            {workflow.is_demo ? (
              <div className="sample-explanation">
                <ShieldCheck size={21} />
                <div>
                  <h4>A preview of what’s possible.</h4>
                  <p>
                    This example helps you explore the process. Approve folders and observe a real
                    workflow to configure and run your own automation.
                  </p>
                </div>
              </div>
            ) : !workflow.can_automate ? (
              <div className="notice">
                This pattern is visible for review. The current runner supports file renaming,
                moving, and invoice tracker updates.
              </div>
            ) : (
              <>
                <ol className="review-stepper" aria-label="Automation approval progress">
                  {['Configure', 'Preview changes', 'Approve & run'].map((label, index) => (
                    <li
                      className={
                        index === (approval ? 2 : preview ? 1 : 0)
                          ? 'current'
                          : index < (approval ? 2 : preview ? 1 : 0)
                            ? 'complete'
                            : ''
                      }
                      key={label}
                    >
                      <span>
                        {index < (approval ? 2 : preview ? 1 : 0) ? <Check size={12} /> : index + 1}
                      </span>
                      {label}
                    </li>
                  ))}
                </ol>
                {!preview ? (
                  <form id="automation-form" onSubmit={submit}>
                    <fieldset disabled={prepare.isPending}>
                      <div className="builder-fields">
                        <Field
                          label="Source file"
                          placeholder="Full path to a file you want to organize"
                          value={params.source_file}
                          onChange={(event) => change('source_file', event.target.value)}
                          spellCheck={false}
                          required
                          hint="Choose an existing file inside an approved folder."
                        />
                        <div className="form-grid">
                          <Field
                            label="New filename or template"
                            placeholder="For example: {stem}_organized.pdf"
                            value={params.new_name}
                            onChange={(event) => change('new_name', event.target.value)}
                            spellCheck={false}
                            hint="Optional. Use {stem} or {date} (the preview date); include the extension."
                          />
                        </div>
                        <section className="destination-review" aria-label="Destination suggestion">
                          <h4>Is this the right destination?</h4>
                          {destinationMode === 'keep' ? (
                            <p>This file will stay in its current folder.</p>
                          ) : destinationMode === 'manual' ? (
                            <Field
                              label="Destination folder"
                              placeholder="Full path to an approved destination"
                              value={params.destination_folder}
                              onChange={(event) => change('destination_folder', event.target.value)}
                              spellCheck={false}
                              hint="Choose a folder within your approved locations."
                            />
                          ) : !source ? (
                            <p>
                              Choose a source file above. We’ll suggest where it belongs from your
                              previous moves.
                            </p>
                          ) : destination.isFetching || lookupSource !== source ? (
                            <Loading label="Finding a destination from your previous moves…" />
                          ) : (
                            <>
                              <ErrorNotice error={destination.error} />
                              {proposedFolder ? (
                                <code className="destination-path">{proposedFolder}</code>
                              ) : null}
                              {destinationData ? (
                                <p>
                                  {destinationConfirmed
                                    ? 'You selected this folder for the current file.'
                                    : destinationData.reason}
                                </p>
                              ) : null}
                              {!proposedFolder && destinationData?.candidates.length ? (
                                <div className="destination-candidates">
                                  {destinationData.candidates.map((candidate) => (
                                    <div className="destination-candidate" key={candidate.folder}>
                                      <div>
                                        <code>{candidate.folder}</code>
                                        <small>
                                          {candidate.examples} previous example
                                          {candidate.examples === 1 ? '' : 's'}
                                        </small>
                                      </div>
                                      <Button
                                        type="button"
                                        variant="secondary"
                                        onClick={() => confirmDestination(candidate.folder)}
                                      >
                                        Use {fileName(candidate.folder)}
                                      </Button>
                                    </div>
                                  ))}
                                </div>
                              ) : null}
                            </>
                          )}
                          {destinationConfirmed ? (
                            <p className="destination-confirmed" role="status">
                              Destination confirmed. Review the exact changes next.
                            </p>
                          ) : null}
                          <div className="destination-actions">
                            {destinationMode === 'manual' ? (
                              <Button
                                type="button"
                                variant="secondary"
                                disabled={
                                  !source ||
                                  !params.destination_folder.trim() ||
                                  destinationConfirmed
                                }
                                onClick={() => confirmDestination(params.destination_folder)}
                              >
                                Use this folder
                              </Button>
                            ) : proposedFolder && !destinationConfirmed ? (
                              <Button
                                type="button"
                                variant="secondary"
                                disabled={destination.isFetching}
                                onClick={() => confirmDestination(proposedFolder)}
                              >
                                Use this folder
                              </Button>
                            ) : null}
                            {destinationMode !== 'manual' ? (
                              <Button type="button" variant="ghost" onClick={editDestination}>
                                Edit destination
                              </Button>
                            ) : null}
                            {destinationMode !== 'auto' ? (
                              <Button
                                type="button"
                                variant="ghost"
                                onClick={() => {
                                  setDestinationMode('auto')
                                  setConfirmedSource(null)
                                }}
                              >
                                Suggest a destination
                              </Button>
                            ) : null}
                            {destinationMode !== 'keep' ? (
                              <Button type="button" variant="ghost" onClick={keepDestination}>
                                Keep current folder
                              </Button>
                            ) : null}
                          </div>
                          {destinationMode === 'auto' ? (
                            <small>
                              Suggestions use file names and your local move history. Unclear names
                              need your choice.
                            </small>
                          ) : null}
                        </section>
                        <label className="checkbox-label extraction-toggle">
                          <input
                            type="checkbox"
                            checked={params.extract_invoice}
                            onChange={(event) => {
                              change('extract_invoice', event.target.checked)
                              if (!event.target.checked) change('tracker_file', '')
                            }}
                          />
                          <span>
                            <strong>Read invoice fields from this PDF</strong>
                            <span className="checkbox-description">
                              Preview reads text-based PDFs locally. Scanned documents need OCR and
                              are not supported yet.
                            </span>
                          </span>
                        </label>
                        {params.extract_invoice ? (
                          <div className="invoice-options">
                            <div className="form-grid form-grid-three">
                              <Field
                                label="Invoice number override"
                                placeholder="Read from PDF"
                                value={params.invoice_number}
                                onChange={(event) => change('invoice_number', event.target.value)}
                              />
                              <Field
                                label="Invoice date override"
                                placeholder="YYYY-MM-DD"
                                value={params.invoice_date}
                                onChange={(event) => change('invoice_date', event.target.value)}
                              />
                              <Field
                                label="Amount override"
                                placeholder="0.00"
                                value={params.invoice_amount}
                                onChange={(event) => change('invoice_amount', event.target.value)}
                              />
                            </div>
                            <p className="field-hint">
                              Leave overrides empty to read the PDF. Naming also supports{' '}
                              {'{invoice_number}'}, {'{invoice_date}'}, and {'{amount}'}.
                            </p>
                            <div className="form-grid">
                              <Field
                                label="Excel tracker (optional)"
                                placeholder="Full path to Tracker.xlsx"
                                value={params.tracker_file}
                                onChange={(event) => change('tracker_file', event.target.value)}
                                spellCheck={false}
                              />
                              <Field
                                label="Tracker sheet"
                                value={params.tracker_sheet}
                                onChange={(event) => change('tracker_sheet', event.target.value)}
                                required={Boolean(params.tracker_file)}
                                maxLength={31}
                              />
                            </div>
                            <p className="field-hint">
                              Columns A–D: invoice number, date, amount, and final file path.
                              Existing workbooks are backed up before editing.
                            </p>
                          </div>
                        ) : null}
                      </div>
                    </fieldset>
                    <ErrorNotice error={prepare.error} />
                  </form>
                ) : (
                  <div className="plan-preview">
                    <div className="preview-heading">
                      <h4>Exact changes to review</h4>
                      <Button variant="ghost" onClick={edit}>
                        <ArrowLeft size={14} />
                        Edit inputs
                      </Button>
                    </div>
                    {Object.keys(preview.plan.extracted_fields).length ? (
                      <dl className="invoice-fields">
                        {Object.entries(preview.plan.extracted_fields).map(([key, value]) => (
                          <div key={key}>
                            <dt>{key.replaceAll('_', ' ')}</dt>
                            <dd>{value}</dd>
                          </div>
                        ))}
                      </dl>
                    ) : null}
                    <ol className="preview-actions">
                      {preview.plan.actions.map((action, index) => (
                        <li key={index}>
                          <span className="step-number">{index + 1}</span>
                          <div>
                            <strong>{actionLabels[action.kind]}</strong>
                            <p>{action.description}</p>
                            <code>{action.source}</code>
                            {action.target ? (
                              <>
                                <ArrowRight size={14} />
                                <code>{action.target}</code>
                              </>
                            ) : null}
                            {action.values.length ? (
                              <div className="tracker-values">
                                {action.values.map((value, column) => (
                                  <span key={column}>
                                    <b>{String.fromCharCode(65 + column)}</b>
                                    {value}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </div>
                        </li>
                      ))}
                    </ol>
                    <p className="preview-expiry">
                      {expired
                        ? 'This preview expired. Edit inputs and create a fresh preview.'
                        : `Valid until ${dateTime(preview.expires_at)}. Changing files or folder permissions invalidates this plan.`}
                    </p>
                    <ErrorNotice error={approve.error || execute.error} />
                    {approval ? (
                      <div className="notice notice-success" role="status">
                        <CheckCircle2 size={18} />
                        <span>Approved for one run. Select “Run automation” to start.</span>
                      </div>
                    ) : (
                      <div className="preview-assurance">
                        <ShieldCheck size={17} />
                        <span>
                          Approval applies only to these changes and this version of the files.
                        </span>
                      </div>
                    )}
                    {!agentConnected && approval ? (
                      <p className="notice">
                        Your agent is offline. Start it before running this automation.
                      </p>
                    ) : null}
                  </div>
                )}
              </>
            )}
          </div>
          <div className="dialog-footer">
            <span className="footer-privacy">
              <ShieldCheck size={15} />
              Your files stay on this device
            </span>
            {workflow.is_demo || !workflow.can_automate ? (
              <Button onClick={() => go('settings')}>
                Set up your folders
                <ArrowRight size={16} />
              </Button>
            ) : !preview ? (
              <Button
                form="automation-form"
                type="submit"
                busy={prepare.isPending}
                disabled={!destinationReady}
              >
                <FileCheck2 size={17} />
                Preview changes
              </Button>
            ) : !approval ? (
              <Button busy={approve.isPending} disabled={expired} onClick={() => approve.mutate()}>
                <Check size={17} />
                Approve this plan
              </Button>
            ) : (
              <Button
                busy={execute.isPending}
                disabled={expired || !agentConnected}
                onClick={() => execute.mutate()}
              >
                <Play size={16} />
                Run automation
              </Button>
            )}
          </div>
        </>
      )}
    </Dialog>
  )
}
