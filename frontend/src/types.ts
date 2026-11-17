export type Source = 'real' | 'demo'
export type Page = 'overview' | 'activity' | 'workflows' | 'runs' | 'settings'

export interface Settings {
  approved_folders: string[]
  monitoring_enabled: boolean
  consent_at: string | null
  scope_revision: number
  minimum_support: number
  retention_days: number
  ai_enabled: boolean
  openai_configured: boolean
  openai_model: string
  data_directory: string
}

export interface AgentStatus {
  connected: boolean
  watching: number
  last_seen: string | null
  error: string | null
  dropped_events: number
}

export interface ActivityEvent {
  id: number
  event_id: string
  timestamp: string
  event_type: 'file_created' | 'file_renamed' | 'file_moved' | 'file_modified'
  file_path: string | null
  old_path: string | null
  new_path: string | null
  is_demo: boolean
}

export interface Workflow {
  id: number
  title: string
  sequence: string[]
  steps: string[]
  frequency: number
  median_seconds: number
  potential_seconds: number
  last_seen: string
  is_demo: boolean
  can_automate: boolean
  last_run_status?: RunStatus | null
  sample_paths: { source: string | null; destination: string | null; tracker: string | null }
}

export interface Dashboard {
  source: Source
  demo_available: boolean
  stats: {
    observed_events: number
    workflow_count: number
    potential_seconds: number
    successful_runs: number
  }
  activity: { date: string; count: number }[]
  workflows: Workflow[]
  recent_events: ActivityEvent[]
  agent: AgentStatus
  settings: Settings
}

export interface Suggestion {
  title: string
  summary: string
  steps: string[]
  rationale: string
  provider: 'local' | 'openai'
  notice: string | null
}

export interface AutomationParams {
  source_file: string
  new_name: string
  destination_folder: string
  extract_invoice: boolean
  tracker_file: string
  tracker_sheet: string
  invoice_number: string
  invoice_date: string
  invoice_amount: string
}

export interface DestinationSuggestion {
  source_file: string
  destination_folder: string | null
  status: 'suggested' | 'uncertain' | 'no_history'
  reason: string
  candidates: {
    folder: string
    examples: number
    matched_words: string[]
    reason: string
  }[]
}

export interface PlanAction {
  kind: 'extract_pdf' | 'rename' | 'move' | 'append_excel'
  source: string
  target: string | null
  sheet: string | null
  values: (string | number)[]
  description: string
}

export interface FrozenPlan {
  version: number
  actions: PlanAction[]
  fingerprints: Record<string, string | null>
  scope_revision: number
  extracted_fields: Record<string, string>
}

export interface Preview {
  id: string
  workflow_id: number
  plan: FrozenPlan
  expires_at: string
}

export interface BatchItem {
  workflow_id: number
  workflow_title: string
  source_file: string
  new_name: string
  destination_folder: string
  reason: string
  candidates: DestinationSuggestion['candidates']
  preview_id: string | null
  plan: FrozenPlan | null
  expires_at: string | null
  status: 'ready' | 'needs_destination' | 'error'
}

export interface BatchSimulation {
  items: BatchItem[]
}

export interface BatchRunResult {
  run_ids: string[]
  count: number
}

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'needs_review'
export interface Run {
  id: string
  title: string
  workflow_id: number
  status: RunStatus
  created_at: string
  started_at: string | null
  finished_at: string | null
  plan: FrozenPlan
  error: string | null
  result: {
    steps: { index: number; kind: string; description: string; status: string; backup?: string }[]
    backups?: string[]
    duration_seconds?: number
  } | null
}
