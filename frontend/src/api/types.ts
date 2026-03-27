/**
 * TypeScript type definitions matching backend Pydantic models
 *
 * References:
 * - Plan v3.3 §2.5: Task status models (JobStatusItem, TaskJobsStatusResponse, etc.)
 * - Plan v3.3 §2.2: Unified response format
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
// Job Status Types (§2.5)
// ============================================

/**
 * Derived states for UI display
 * Mapped from jobflow-remote raw states by backend
 */
export type DerivedState = 'RUNNING' | 'COMPLETED' | 'FAILED' | 'PENDING' | 'PAUSED' | 'ERROR'

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
}

// ============================================
// Task Summary Types (§2.5)
// ============================================

/**
 * Task summary for list display
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

// ============================================
// Structure Validation Types
// ============================================

/**
 * POSCAR validation request
 */
export interface ValidatePoscarRequest {
  content: string
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
}

// ============================================
// Input Types (matching backend Pydantic models)
// ============================================

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
  parameters: string
}

/** NVE input parameters */
export interface NVEInput {
  nodes?: number | null
  kspacing: number
  md_dt: number
  md_step: number
  scf_thr: number
  parameters: string
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

/** Basic input */
export interface BasicInput {
  software: 'vasp' | 'cp2k' | 'siesta' | 'abacus' | 'openmx'
  plot: boolean
}

/** Top-level InputT payload for /submit */
export interface InputT {
  basic_input: BasicInput
  scheduler_config: Record<string, never>
  nvt_input?: NVTInput | null
  nve_input?: NVEInput | null
  scf_input?: SCFInput | null
  prenamd_input?: PreNAMDInput | null
  namd_input?: NAMDInput | null
  steps: Array<'nvt' | 'nve' | 'scf' | 'pre_namd' | 'namd'>
  stru: string
  stru_format: string
}
