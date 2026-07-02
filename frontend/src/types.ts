export type SourceKind = 'metric_view' | 'dashboard' | 'genie_space'
export type DeliveryKind = 'pbip' | 'pbit' | 'xmla'

export interface MetricViewSummary {
  fully_qualified_name: string
  owner: string | null
  updated_at: string | null
  description: string | null
}

export interface CatalogSummary {
  name: string
}

export interface SchemaSummary {
  name: string
}

export interface DashboardSummary {
  id: string
  name: string
  owner: string | null
  updated_at: string | null
}

export interface GenieSpaceSummary {
  id: string
  name: string
  owner: string | null
  updated_at: string | null
}

export interface FabricWorkspaceSummary {
  id: string
  name: string
  is_dedicated_capacity: boolean
  capacity_id: string | null
}

export interface SyncSourceRef { kind: SourceKind; id: string }
export interface SyncTarget { kind: DeliveryKind; target_id: string }

export interface SyncRequest {
  sources: SyncSourceRef[]
  target: SyncTarget
  model_name: string
  description?: string | null
  xmla_merge?: boolean
  storage_modes?: Record<string, string>
}

export interface TableInfo {
  name: string
  storage_mode: 'import' | 'direct_query' | 'dual'
  uc_path: string | null
  column_count: number
  is_measures_table: boolean
}

export interface HistoryEntry {
  run_id: string
  created_at: string
  model_name: string | null
  state: string
  summary_created: number
  summary_updated: number
  summary_needs_manual_review: number
  validation_status: string
  val_passed: number
  val_failed: number
  val_skipped: number
}

export interface RunDetail {
  run_id: string
  created_at: string
  run_by: string | null
  model_name: string | null
  delivery: string
  state: string
  validation_status: string
  report: SyncReport
  validation: ValidationReport | null
  sources: SyncSourceRef[]
  dataset_id: string | null
  workspace_id: string | null
  val_dimension: string | null
  val_timeframe: string | null
}

export interface DimValue {
  key: string | null
  sql: number | null
  dax: number | null
  delta: number | null
  matched: boolean
}

export interface MeasureValidation {
  name: string
  status: 'passed' | 'failed' | 'skipped'
  dim_used: string | null
  scalar_sql: number | null
  scalar_dax: number | null
  scalar_delta: number | null
  scalar_matched: boolean | null
  by_dim: DimValue[]
  skip_reason: string | null
  skip_category?: string | null
  skip_detail?: string | null
  failed_side?: 'source_sql' | 'dax' | 'setup' | null
}

export interface ValidationSummary {
  passed: number
  failed: number
  skipped: number
}

export interface ValidationReport {
  model: string
  dataset_id: string
  workspace_id: string
  epsilon: number
  ran_at: string
  results: MeasureValidation[]
  summary: ValidationSummary
}

export interface ValidateRequest {
  sources: SyncSourceRef[]
  model_name: string
  dataset_id: string
  workspace_id: string
  dim_sql_ref?: string | null
  timeframe?: 'all' | 'day' | 'week' | 'month' | 'quarter' | 'year'
  date_table?: string | null
  date_column?: string | null
  exclude_measures?: string[]
  run_id?: string | null
}

export interface SyncReport {
  run_id: string
  mode: 'preview' | 'apply'
  delivery: string
  summary: {
    created: number
    updated: number
    unchanged: number
    deleted?: number
    renamed?: number
    skipped?: number
    needs_manual_review: number
  }
  outcomes: SyncOutcome[]
  errors?: ReportError[]
  fatal_error?: ReportError | null
  tables?: TableInfo[]
  validation?: ValidationReport | null
  published_dataset_id?: string | null
}

export interface SyncOutcome {
  name: string
  object_kind: 'table' | 'measure' | 'relationship' | 'dimension'
  action: 'created' | 'updated' | 'unchanged' | 'deleted' | 'renamed' | 'skipped'
  translation_method: 'rule' | 'cache' | 'llm' | 'placeholder' | 'n/a' | null
  sql_expression: string | null
  dax: string | null
  warnings: string[]
  needs_manual_review: boolean
  diff_preview: string | null
}

export interface ReportError {
  code: string
  message: string
  suggestion?: string | null
  docs_link?: string | null
}

export type ApiError = ReportError

export interface CacheStatus {
  entries: number
  bytes: number
  path: string
}

export interface WarehouseSummary {
  id: string
  name: string
  state: string | null
  size: string | null
  serverless: boolean | null
}

export interface StartValidationResponse {
  job_id: string
  total: number
}

export interface ValidationJobStatus {
  status: 'pending' | 'running' | 'done' | 'error' | 'canceled'
  total: number
  results: MeasureValidation[]
  summary: ValidationSummary
  error: string | null
  current: string | null
}

export interface DateColumnRef {
  table: string
  column: string
}

export interface ValidationDimensionsResponse {
  dimensions: string[]
  has_date_column: boolean
  date_columns: DateColumnRef[]
}
