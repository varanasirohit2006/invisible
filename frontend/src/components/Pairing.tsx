import { useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowRight, FolderCheck, KeyRound, ShieldCheck, Workflow } from 'lucide-react'
import { useMutation } from '@tanstack/react-query'
import { post } from '../api'
import { Brand } from './Shell'
import { Button, ErrorNotice, Field } from './ui'

export function Pairing({
  onConnect,
  connectionError,
}: {
  onConnect: () => void
  connectionError?: Error | null
}) {
  const [token, setToken] = useState('')
  const mutation = useMutation({
    mutationFn: () => post('/session', { token: token.trim() }),
    onSuccess: () => {
      setToken('')
      onConnect()
    },
  })
  function submit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate()
  }
  return (
    <main className="pairing-page">
      <div className="pairing-layout">
        <section className="pairing-story">
          <Brand />
          <div className="pairing-copy">
            <h1>
              Less busywork.
              <br />
              <span>More breathing room.</span>
            </h1>
            <p>
              Find the small routines that fill your day, and turn them into automations you
              control.
            </p>
            <div className="pairing-benefits">
              <div>
                <FolderCheck />
                <span>Observe only folders you approve</span>
              </div>
              <div>
                <Workflow />
                <span>Discover the patterns in your work</span>
              </div>
              <div>
                <ShieldCheck />
                <span>Review every change before it runs</span>
              </div>
            </div>
          </div>
          <span className="pairing-footer">Built for your work. Kept on your device.</span>
        </section>
        <section className="pairing-form-panel">
          <div className="pairing-key">
            <KeyRound size={27} />
          </div>
          <h2>Connect your workspace</h2>
          <p>Enter the pairing token from your local launcher to open your private dashboard.</p>
          <form onSubmit={submit}>
            <Field
              label="Local pairing token"
              placeholder="Paste your pairing token"
              value={token}
              onChange={(event) => setToken(event.target.value)}
              type="password"
              autoComplete="off"
              spellCheck={false}
              required
              autoFocus
            />
            <ErrorNotice error={mutation.error || connectionError} />
            <Button
              type="submit"
              busy={mutation.isPending}
              disabled={!token.trim()}
              className="full-width"
            >
              Open workspace
              <ArrowRight size={17} />
            </Button>
          </form>
          <details className="pairing-help">
            <summary>Where do I find my token?</summary>
            <p>
              Start the app with <code>python run.py --show-token</code>. The token also lives in
              the app’s private data folder, printed by the launcher. Keep it on this device.
            </p>
          </details>
          <div className="pairing-assurance">
            <ShieldCheck size={16} />
            <span>Connecting does not enable monitoring.</span>
          </div>
        </section>
      </div>
    </main>
  )
}
