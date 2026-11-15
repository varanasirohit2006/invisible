import { useState } from 'react'
import type { FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Check,
  Database,
  Folder,
  FolderPlus,
  LockKeyhole,
  Plus,
  Save,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react'
import { api, put, remove } from '../api'
import type { Settings } from '../types'
import { Button, Dialog, ErrorNotice, Loading, PageHeading } from '../components/ui'

export function SettingsPage() {
  const settings = useQuery({
    queryKey: ['settings'],
    queryFn: ({ signal }) => api<Settings>('/settings', { signal }),
  })
  return (
    <>
      <PageHeading
        title="Your workspace. Your rules."
        description="Choose what to observe, what to keep, and what stays entirely local."
      />
      <ErrorNotice error={settings.error} />
      {settings.isPending ? (
        <Loading label="Loading permissions…" />
      ) : settings.data ? (
        <SettingsForm initial={settings.data} />
      ) : null}
    </>
  )
}

function SettingsForm({ initial }: { initial: Settings }) {
  const client = useQueryClient()
  const [form, setForm] = useState(initial)
  const [folder, setFolder] = useState('')
  const [consent, setConsent] = useState(false)
  const [confirmation, setConfirmation] = useState(false)
  const [folderError, setFolderError] = useState('')
  const [saved, setSaved] = useState(false)
  const needsConsent =
    form.approved_folders.length > 0 &&
    (!initial.consent_at ||
      JSON.stringify(form.approved_folders) !== JSON.stringify(initial.approved_folders))
  const save = useMutation({
    mutationFn: () =>
      put<Settings>('/settings', {
        approved_folders: form.approved_folders,
        monitoring_enabled: form.monitoring_enabled,
        minimum_support: form.minimum_support,
        retention_days: form.retention_days,
        ai_enabled: form.ai_enabled,
        consent,
      }),
    onSuccess: async (settings) => {
      setForm(settings)
      setConsent(false)
      setSaved(true)
      client.setQueryData(['settings'], settings)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['dashboard'] }),
        client.invalidateQueries({ queryKey: ['workflows'] }),
      ])
    },
  })
  const clear = useMutation({
    mutationFn: () => remove('/events', { source: 'real', confirm: true }),
    onSuccess: async () => {
      setConfirmation(false)
      await client.invalidateQueries({
        predicate: (query) =>
          ['dashboard', 'events', 'workflows'].includes(String(query.queryKey[0])),
      })
    },
  })
  function update<K extends keyof Settings>(key: K, value: Settings[K]) {
    setForm((old) => ({ ...old, [key]: value }))
    setSaved(false)
  }
  function addFolder() {
    if (!folder.trim()) {
      setFolderError('Enter the full path of a local folder.')
      return
    }
    if (form.approved_folders.includes(folder.trim())) {
      setFolderError('That folder is already in the list.')
      return
    }
    if (form.approved_folders.length >= 20) {
      setFolderError('You can approve at most 20 folders.')
      return
    }
    update('approved_folders', [...form.approved_folders, folder.trim()])
    setFolder('')
    setFolderError('')
    setConsent(false)
  }
  function submit(event: FormEvent) {
    event.preventDefault()
    save.mutate()
  }
  return (
    <>
      <form className="settings-layout" onSubmit={submit}>
        <div className="settings-sections">
          <section className="panel settings-section">
            <div className="section-title">
              <span className="section-icon">
                <FolderPlus size={22} />
              </span>
              <div>
                <h2>Approved folders</h2>
                <p>Only activity inside these folders can be observed.</p>
              </div>
            </div>
            <div className="folder-list">
              {form.approved_folders.length ? (
                form.approved_folders.map((path) => (
                  <div className="folder-row" key={path}>
                    <Folder size={18} />
                    <code>{path}</code>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={`Remove ${path}`}
                      onClick={() => {
                        update(
                          'approved_folders',
                          form.approved_folders.filter((value) => value !== path),
                        )
                        setConsent(false)
                      }}
                    >
                      <X size={16} />
                    </button>
                  </div>
                ))
              ) : (
                <p className="empty-folder-note">
                  No folders approved yet. Start with a folder you use for repetitive work.
                </p>
              )}
            </div>
            <div className="add-folder">
              <input
                aria-label="Folder path"
                placeholder="C:\Users\you\Documents\Invoices"
                value={folder}
                onChange={(event) => {
                  setFolder(event.target.value)
                  setFolderError('')
                }}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault()
                    addFolder()
                  }
                }}
                spellCheck={false}
              />
              <Button
                type="button"
                variant="secondary"
                onClick={addFolder}
                disabled={form.approved_folders.length >= 20}
              >
                <Plus size={16} />
                Add folder
              </Button>
            </div>
            <ErrorNotice error={folderError} />
            {needsConsent ? (
              <label className="checkbox-label consent-box">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(event) => setConsent(event.target.checked)}
                  required
                />
                <span>
                  I approve file activity monitoring and individually reviewed automation within
                  these folders.
                </span>
              </label>
            ) : null}
            <div className="setting-toggle-row">
              <div>
                <strong>Activity monitoring</strong>
                <p>Pause anytime. No keystrokes, screenshots, or app tracking.</p>
              </div>
              <button
                type="button"
                role="switch"
                aria-label="Activity monitoring"
                aria-checked={form.monitoring_enabled}
                className={`switch ${form.monitoring_enabled ? 'switch-on' : ''}`}
                onClick={() => update('monitoring_enabled', !form.monitoring_enabled)}
              >
                <span />
              </button>
            </div>
          </section>
          <section className="panel settings-section">
            <div className="section-title">
              <span className="section-icon">
                <Sparkles size={21} />
              </span>
              <div>
                <h2>Discovery & recommendations</h2>
                <p>Decide how often a routine should repeat before it appears.</p>
              </div>
            </div>
            <div className="form-grid">
              <div className="field">
                <label htmlFor="support">Minimum repeated sessions</label>
                <select
                  id="support"
                  value={form.minimum_support}
                  onChange={(event) => update('minimum_support', Number(event.target.value))}
                >
                  {[2, 3, 5, 10, 20].map((value) => (
                    <option key={value} value={value}>
                      {value} sessions
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="retention">Keep activity for</label>
                <select
                  id="retention"
                  value={form.retention_days}
                  onChange={(event) => update('retention_days', Number(event.target.value))}
                >
                  {[7, 30, 90, 365].map((value) => (
                    <option key={value} value={value}>
                      {value} days
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <div className="ai-setting">
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={form.ai_enabled}
                  disabled={!initial.openai_configured && !form.ai_enabled}
                  onChange={(event) => update('ai_enabled', event.target.checked)}
                />
                <span>
                  <strong>Use OpenAI for workflow explanations</strong>
                  <span className="checkbox-description">
                    When you review a workflow, send only normalized action types, file extensions,
                    and aggregate statistics. File paths and contents stay on this device.
                  </span>
                </span>
              </label>
              <p className="provider-note">
                {initial.openai_configured
                  ? `Available model: ${initial.openai_model}. This optional service uses your OpenAI account.`
                  : 'Local explanations are ready to use. To enable OpenAI, set OPENAI_API_KEY locally and restart the app.'}
              </p>
            </div>
          </section>
          <section className="panel settings-section">
            <div className="section-title">
              <span className="section-icon">
                <Database size={21} />
              </span>
              <div>
                <h2>Local storage</h2>
                <p>Activity, settings, run history, and workbook backups stay here.</p>
              </div>
            </div>
            <code className="storage-path">{initial.data_directory}</code>
            <div className="storage-actions">
              <p>
                Clear real activity and discovered patterns. Run history and backups are retained.
              </p>
              <Button type="button" variant="ghost" onClick={() => setConfirmation(true)}>
                <Trash2 size={15} />
                Clear activity
              </Button>
            </div>
          </section>
          <ErrorNotice error={save.error} />
          <div className="settings-save">
            <span role="status">
              {saved ? (
                <>
                  <Check size={17} />
                  Settings saved
                </>
              ) : (
                'Changes apply when you save.'
              )}
            </span>
            <Button type="submit" busy={save.isPending} disabled={needsConsent && !consent}>
              <Save size={16} />
              Save settings
            </Button>
          </div>
        </div>
        <aside className="permissions-panel">
          <ShieldCheck size={29} strokeWidth={1.5} />
          <h2>Built around your permission.</h2>
          <p>Observation and automation are separate decisions.</p>
          <div>
            <LockKeyhole size={17} />
            <span>Only approved folders are in scope.</span>
          </div>
          <div>
            <Check size={17} />
            <span>Every run needs a fresh preview and your approval.</span>
          </div>
          <div>
            <Database size={17} />
            <span>Existing files are never replaced by a move or rename.</span>
          </div>
          <p className="permissions-footnote">
            Pausing stops observation. Remove a folder and save to revoke access and invalidate
            pending approvals.
          </p>
        </aside>
      </form>
      {confirmation ? (
        <Dialog title="Clear your activity log?" onClose={() => setConfirmation(false)}>
          <div className="dialog-body">
            <p>
              This removes real activity and discovered patterns from this device. Run history and
              workbook backups remain. If monitoring is enabled, new activity will continue to
              appear.
            </p>
            <ErrorNotice error={clear.error} />
          </div>
          <div className="dialog-footer">
            <Button variant="secondary" onClick={() => setConfirmation(false)}>
              Keep activity
            </Button>
            <Button variant="danger" busy={clear.isPending} onClick={() => clear.mutate()}>
              Clear real activity
            </Button>
          </div>
        </Dialog>
      ) : null}
    </>
  )
}
