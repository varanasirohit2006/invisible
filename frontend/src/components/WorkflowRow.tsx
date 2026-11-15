import { ArrowRight, Clock3, FileImage, FileSpreadsheet, Files, Sparkles } from 'lucide-react'
import type { Workflow } from '../types'
import { duration, number } from '../format'

export function WorkflowRow({
  workflow,
  onReview,
}: {
  workflow: Workflow
  onReview: (workflow: Workflow) => void
}) {
  const Icon = workflow.sequence.some((step) => step.includes('xlsx') || step.includes('csv'))
    ? FileSpreadsheet
    : workflow.sequence.some((step) => /png|jpg|jpeg/.test(step))
      ? FileImage
      : Files
  return (
    <article className="workflow-row">
      <div className="workflow-icon">
        <Icon size={23} strokeWidth={1.6} />
      </div>
      <div className="workflow-main">
        <div className="workflow-title-line">
          <h3>{workflow.title}</h3>
          {workflow.is_demo ? <span className="small-tag">Sample</span> : null}
        </div>
        <div
          className="workflow-sequence"
          aria-label={`Observed steps: ${workflow.steps.join(', ')}`}
        >
          {workflow.steps.map((step, index) => (
            <span key={`${step}-${index}`}>
              {index ? <ArrowRight size={12} aria-hidden="true" /> : null}
              <span>{step}</span>
            </span>
          ))}
        </div>
        <div className="workflow-meta">
          <span>{number(workflow.frequency)} occurrences</span>
          <span className="meta-dot">·</span>
          <span>
            <Clock3 size={12} />
            {duration(workflow.median_seconds)} observed / session
          </span>
        </div>
      </div>
      <div className="workflow-value">
        <strong>{duration(workflow.potential_seconds)}</strong>
        <span>potential savings</span>
      </div>
      <button className="review-button" type="button" onClick={() => onReview(workflow)}>
        Review
        <ArrowRight size={15} />
      </button>
    </article>
  )
}

export function WorkflowHint() {
  return (
    <p className="estimate-note">
      <Sparkles size={14} />
      Savings are estimates based on 80% of observed elapsed time, not active work measurements.
    </p>
  )
}
