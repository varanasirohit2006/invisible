import { useEffect, useId, useRef } from 'react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'
import { AlertCircle, ArrowRight, LoaderCircle, X } from 'lucide-react'

export function Button({
  children,
  variant = 'primary',
  busy = false,
  className = '',
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
  busy?: boolean
}) {
  return (
    <button
      {...props}
      disabled={disabled || busy}
      className={`button button-${variant} ${className}`}
    >
      {busy ? <LoaderCircle size={16} className="spin" aria-hidden="true" /> : null}
      {children}
    </button>
  )
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <div className="notice notice-error" role="alert">
      <AlertCircle size={18} aria-hidden="true" />
      <span>{error instanceof Error ? error.message : String(error)}</span>
    </div>
  )
}

export function Loading({ label = 'Loading your workspace…' }: { label?: string }) {
  return (
    <div className="loading-state" role="status">
      <LoaderCircle size={22} className="spin" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">{icon}</div>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  )
}

export function PageHeading({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action ? <div className="page-actions">{action}</div> : null}
    </div>
  )
}

export function Field({
  label,
  hint,
  className = '',
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  const id = useId()
  return (
    <div className={`field ${className}`}>
      <label htmlFor={id}>{label}</label>
      <input {...props} id={id} aria-describedby={hint ? `${id}-hint` : undefined} />
      {hint ? <small id={`${id}-hint`}>{hint}</small> : null}
    </div>
  )
}

export function Dialog({
  title,
  children,
  onClose,
  wide = false,
}: {
  title: string
  children: ReactNode
  onClose: () => void
  wide?: boolean
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  useEffect(() => {
    const dialog = ref.current
    dialog?.showModal()
    return () => dialog?.close()
  }, [])
  return (
    <dialog
      ref={ref}
      className={`dialog ${wide ? 'dialog-wide' : ''}`}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="dialog-shell">
        <div className="dialog-header">
          <h2 id={titleId}>{title}</h2>
          <button className="icon-button" type="button" aria-label="Close dialog" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  )
}

export function TextLink({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button type="button" className="text-link" onClick={onClick}>
      {children}
      <ArrowRight size={15} aria-hidden="true" />
    </button>
  )
}
