/**
 * TypeScript type definitions matching backend Pydantic models
 */

// ============================================
// Common Response Types
// ============================================

/**
 * Unified response wrapper for /frontend/* endpoints
 */
export interface ApiResponse<T> {
  success: boolean
  data?: T
  error?: {
    code: string
    message: string
  }
}

// ============================================
// Job Status Types
// ============================================

/**
 * Derived states for UI display
 * Mapped from jobflow-remote raw states by backend
 */
export type DerivedState = 'RUNNING' | 'COMPLETED' | 'FAILED' | 'PENDING' | 'PAUSED' | 'STOPPED' | 'ERROR' | 'QUEUED' | 'DISPATCHING' | 'CANCELLED'

/**
 * Single job status item (lightweight)
 */
export interface JobStatusItem {
  uuid: string
  name: string
  /** Raw state from jobflow-remote (e.g., BATCH_RUNNING, COMPLETED, FAILED) */
  state: string
  /** Derived state for UI display */
  derived_state: DerivedState | null
  /** Error message if job failed */
  error: string | null
  /** Job index in the flow */
  index: number
  /** Timestamps from jobflow-remote (ISO format strings) */
  created_on?: string | null
  start_time?: string | null
  end_time?: string | null
}

/**
 * Detailed job status response
 */
export interface JobStatusDetailResponse {
  uuid: string
  name: string
  /** Raw state from jobflow-remote */
  state: string
  /** Derived state for UI display */
  derived_state: DerivedState | null
  /** Error message if job failed */
  error: string | null
  /** Note about log availability */
  log_note: string | null
}

/**
 * Task-level jobs status response
 */
export interface TaskJobsStatusResponse {
  task_id: string
  /** Raw status counts from jobflow-remote (e.g., { "COMPLETED": 5, "RUNNING": 2 }) */
  raw_status_counts: Record<string, number>
  /** Derived overall status for the task */
  derived_status: DerivedState
  /** List of all jobs in the task */
  jobs: JobStatusItem[]
  /** Predecessor task id if this is a resume task */
  prev_task_id?: string | null
  /** Custom task display name */
  task_name?: string | null
  /** Structure formula */
  formula?: string | null
}

// ============================================
// Task Summary Types
// ============================================

/**
 * Task summary for list display and resume eligibility
 */
export interface TaskSummary {
  task_id: string
  owner: string
  created_at: number  // Unix timestamp
  /** Raw status counts from jobflow-remote */
  raw_status_counts: Record<string, number>
  /** Derived overall status */
  derived_status: DerivedState
  /** Total number of jobs in the task */
  total_jobs: number
  /** Names of failed jobs (for quick preview) */
  failed_job_names: string[]
  /** Steps included in this task (ordered by phase) */
  steps: string[]
  /** Steps that have fully completed (contiguous prefix) */
  completed_steps: string[]
  /** Structure formula (e.g. "MoS2") */
  formula: string | null
  /** Custom task display name */
  task_name: string | null
  /** Number of atoms in the structure */
  num_atoms: number | null
  /** Predecessor task id if this is a resume task */
  prev_task_id: string | null
  /** Worker used for this task (e.g. "local_slurm", "remote_djs") */
  worker: string | null
  /** The next step eligible for resume */
  resume_next_step: string | null
  /** Whether this task can be resumed */
  resume_eligible: boolean
  /** Queue status: "QUEUED" | "DISPATCHING" | null (for tasks in the waiting queue) */
  queue_status?: string | null
  /** 1-based position in the waiting queue (null if not queued) */
  queue_position?: number | null
  /** Logical pool name (e.g. "local_slurm") */
  pool_name?: string | null
  /** Runtime worker name (e.g. "local_slurm_007") */
  runtime_worker?: string | null
}

/**
 * Task summary list response (paginated)
 */
export interface TaskSummaryListResponse {
  total: number
  items: TaskSummary[]
}

// ============================================
// Task Detail Types
// ============================================

/**
 * Task detail response (extended info)
 * Note: Actual fields depend on backend implementation
 */
export type TaskDetail = TaskJobsStatusResponse

// ============================================
// Auth Types
// ============================================

/**
 * Login request payload
 */
export interface LoginRequest {
  username: string
  password: string
}

/**
 * Login response (JWT token)
 */
export interface LoginResponse {
  access_token: string
  token_type: string
}

/**
 * Register response (same as login - returns JWT)
 */
export type RegisterResponse = LoginResponse

/**
 * Current user info response (GET /auth/me)
 */
export interface UserInfo {
  username: string
}

// ============================================
// System Types
// ============================================

/**
 * Health check response (GET /healthz)
 */
export interface HealthResponse {
  status: 'ok' | 'degraded'
  version: string
  timestamp: number
}

/**
 * Structured response from POST /submit (pool-based mode)
 */
export interface SubmitResponse {
  task_id: string
  status: 'SUBMITTED' | 'QUEUED'
  worker?: string | null
  queue_position?: number | null
}

/**
 * Pool status response from GET /pool/status
 */
export interface PoolStatusResponse {
  pool_name: string
  total_workers: number
  idle_workers: number
  busy_workers: number
  user_occupied_workers: number
}

// ============================================
// Job Error Types
// ============================================

/**
 * Job error detail response
 * Returned by GET /frontend/tasks/{taskId}/jobs/{jobUuid}/error
 */
export interface JobErrorResponse {
  state: string
  available: boolean
  message: string | null
  traceback: string | null
}

// ============================================
// Task Operation Types
// ============================================

/**
 * Stop failed item - describes a single job that failed to stop
 */
export interface StopFailedItem {
  uuid: string
  error: string
}

/**
 * Stop result response
 * Returned by POST /frontend/tasks/{taskId}/stop
 */
export interface StopResultResponse {
  stopped: string[]
  skipped: string[]
  failed: StopFailedItem[]
}

/**
 * Continue result response
 * Returned by POST /frontend/tasks/{taskId}/continue
 */
export interface ContinueResultResponse {
  continued: string[]
  skipped: string[]
  failed: StopFailedItem[]
}

// ============================================
// Structure Validation Types
// ============================================

/**
 * Structure validation request
 */
export interface ValidatePoscarRequest {
  content: string
  /** ASE single-frame format string (vasp/cif/extxyz/openmx-dat).
   *  Backend defaults to "vasp" when omitted (backward compatible). */
  stru_format?: string
}

/**
 * Format-agnostic structure data for 3D rendering.
 * Decoupled from file format. Backend parses via ASE and outputs this.
 */
export interface StructurePreviewPayload {
  species: string[]
  cart_coords: number[][]
  lattice: number[][]
  pbc: boolean[]
  constraint_mask: boolean[] | null
  /** Canonical preview content format (always "vasp"). */
  format?: 'vasp'
  /** Canonical VASP-serialized structure content. */
  content?: string
}

/**
 * POSCAR validation response
 */
export interface ValidatePoscarResponse {
  valid: boolean
  /** Error message if validation failed */
  error?: string
  /** Parsed structure info if valid */
  structure?: {
    num_atoms: number
    formula: string
    lattice: number[][]
  }
  /** 3D structure preview data for rendering */
  preview?: StructurePreviewPayload | null
}

// ============================================
// Job Files, Progress, and Images Types
// ============================================

/**
 * Single file entry from a job's run directory
 */
export interface JobFileItem {
  name: string
  size: number
  url: string
  category: 'input' | 'output' | 'data' | 'image'
}

/**
 * Metadata for a subdirectory in a job's run directory.
 * Returned as part of the initial files listing for lazy-load display.
 */
export interface SubdirInfo {
  name: string
  file_count: number
  /** Status derived from marker files: "completed", "failed", "running", "pending", "unknown" */
  status: string
}

/**
 * Response listing available files in a job's run directory
 */
export interface JobFilesResponse {
  available: boolean
  files: JobFileItem[]
  subdirs: SubdirInfo[]
}

/**
 * Response listing files inside a specific subdirectory (lazy loaded)
 */
export interface SubdirFilesResponse {
  available: boolean
  subdir: string
  files: JobFileItem[]
}

/**
 * SCF batch-level frame statistics
 */
export interface SCFBatchInfo {
  completed: number
  converged: number
  failed: number
  running: number
  pending: number
}

/**
 * Details about the currently running SCF frame
 */
export interface SCFCurrentFrame {
  name: string
  global_index: number
  status: string
  electronic_step_current: number | null
  electronic_step_limit: number | null
  scf_algorithm: string | null
  converged: boolean | null
}

/**
 * Job progress response (MD steps or SCF convergence)
 */
export interface JobProgressResponse {
  available: boolean
  step_type: string | null
  current_step: number
  total_steps: number | null
  percent: number | null
  last_temp: number | null
  last_energy: number | null
  batch: SCFBatchInfo | null
  current_frame: SCFCurrentFrame | null
  failed_frames: string[]
}

/**
 * Single image entry from a job's output
 */
export interface JobImageItem {
  name: string
  url: string
}

/**
 * Response listing result images for a completed job
 */
export interface JobImagesResponse {
  available: boolean
  images: JobImageItem[]
}

// ============================================
// Job Input Parameters Types
// ============================================

/**
 * Response containing input parameters for a job
 * Returned by GET /frontend/tasks/{taskId}/jobs/{jobUuid}/input-params
 */
export interface JobInputParamsResponse {
  available: boolean
  incar: Record<string, string> | null
  kpoints_text: string | null
  parameters: Record<string, string> | null
  parameters_title: string | null
  warning: string | null
}

// ============================================
// MD Timeseries Types
// ============================================

/**
 * Metadata for a single NVT retry attempt
 */
export interface MDAttemptItem {
  attempt: number
  label: string
  is_current: boolean
  archived: boolean
}

/**
 * Time-series arrays for an MD trajectory
 */
export interface MDSeriesData {
  steps: number[]
  time_fs: number[]
  temperatures: number[]
  total_energies: number[]
  potential_energies: number[]
  kinetic_energies: number[]
  converged: boolean[]
}

/**
 * Reference lines and annotation values for the chart
 */
export interface MDReferenceLines {
  potim_fs: number | null
  tebeg: number | null
  teend: number | null
  target_temperature: number | null
  temperature_tolerance_low: number | null
  temperature_tolerance_high: number | null
  mean_total_energy: number | null
  initial_total_energy: number | null
  energy_drift_slope_ev_per_step: number | null
}

/**
 * Summary statistics for the returned timeseries data
 */
export interface MDTimeseriesStats {
  current_step: number
  total_steps: number | null
  original_points: number
  returned_points: number
  sampled: boolean
}

/**
 * Response for the MD timeseries endpoint
 */
export interface JobMdTimeseriesResponse {
  available: boolean
  step_type: string | null
  state: string | null
  selected_attempt: number
  attempts: MDAttemptItem[]
  series: MDSeriesData | null
  references: MDReferenceLines | null
  stats: MDTimeseriesStats | null
  warning: string | null
}

// ============================================
// Input Types (matching backend Pydantic models)
// ============================================

/** Selective dynamics input parameters */
export interface SelDynInput {
  constraint_layers?: string | null
  layer_direction?: string | null
  total_layers?: number | null
}

/** NVT input parameters */
export interface NVTInput {
  nodes?: number | null
  kspacing: number
  md_thermostat: 'nhc' | 'rescale_v'
  md_dt: number
  md_step: number
  temp_begin: number
  temp_end: number
  scf_thr: number
  sel?: SelDynInput
  parameters: string
}

/** DFT calculator input parameters (used as NVE calculator branch for software=vasp) */
export interface DFTBaseInput {
  nodes?: number | null
  kspacing: number
  scf_thr: number
  parameters: string
}

/** NequIP calculator input parameters */
export interface NequipInput {
  version: string
  use_gpu: boolean
  use_pretrained_model: boolean
  model_name: string
  model_hash: string
  energy_unit: string
  length_unit: string
}

/** MACE calculator input parameters */
export interface MACEInput {
  version: string
  use_gpu: boolean
  use_pretrained_model: boolean
  model_name: string
  model_hash: string
  default_dtype: string
}

/** NVE input parameters */
export interface NVEInput {
  md_dt: number
  md_step: number
  software: 'vasp' | 'nequip' | 'mace'
  calculator: DFTBaseInput | NequipInput | MACEInput | Record<string, unknown>
  sel?: SelDynInput
}

/** Request payload for computing constraint mask.
 *  Either stru_content or task_id must be provided. */
export interface ComputeConstraintMaskRequest {
  stru_content?: string
  stru_format?: string
  task_id?: string
  constraint_layers: string
  layer_direction: string
  total_layers: number
}

/** Response from constraint mask computation */
export interface ComputeConstraintMaskResponse {
  constraint_mask: boolean[]
  source: 'file' | 'layers'
  warning: string | null
}

/** SCF input parameters */
export interface SCFInput {
  nodes?: number | null
  kspacing: number
  scf_thr: number
  scf_step: number
  batch_size: number
  is_alle: boolean
  parameters: string
}

/** Pre-NAMD advanced options */
export interface PreNAMDInputAdv {
  reorder: boolean
  alle: boolean
  ikpt: number
  ispin: number
  which_atoms?: number[] | null
  cbar_labels?: string[] | null
}

/** Pre-NAMD input parameters */
export interface PreNAMDInput {
  bmin: number | string
  bmax: number | string
  md_dt: number
  adiabatic_rep: boolean
  surface_hopping: 'FSSH' | 'DISH'
  adv: PreNAMDInputAdv
}

/** NAMD input parameters */
export interface NAMDInput {
  nodes?: number | null
  md_dt: number
  adiabatic_rep: boolean
  surface_hopping: 'FSSH' | 'DISH'
  nsample: number
  ntraj: number
  nelm: number
  namdtime: number
  temperature: number
  lhole: boolean
  inibands: number[]
}

/** Top-level InputT payload for /submit */
export interface InputT {
  plot: boolean
  scheduler_config: Record<string, never>
  nvt_input?: NVTInput | null
  nve_input?: NVEInput | null
  scf_input?: SCFInput | null
  prenamd_input?: PreNAMDInput | null
  namd_input?: NAMDInput | null
  steps: Array<'nvt' | 'nve' | 'scf' | 'pre_namd' | 'namd' | 'fused_scf_prenamd'>
  stru: string
  stru_format: string
  stru_hash?: string
  task_name?: string | null
}
