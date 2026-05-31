/**
 * Centralized step name constants and label mappings.
 *
 * These values are used across TaskCard, ResumeTaskSelector, StepSelector,
 * JobStepTimeline, SubmitTaskPage, and TaskDetailPage.
 */

/** The fused SCF + Pre-NAMD step identifier */
export const FUSED_SCF_PRENAMD = 'fused_scf_prenamd' as const

/**
 * Human-readable labels for workflow steps.
 * Used in ResumeTaskSelector, JobStepTimeline, and other full-label contexts.
 */
export const STEP_LABELS: Record<string, string> = {
  nvt: 'NVT',
  nve: 'NVE',
  scf: 'SCF',
  pre_namd: 'Pre-NAMD',
  namd: 'NAMD',
  [FUSED_SCF_PRENAMD]: 'Fused SCF+Pre-NAMD',
}

/**
 * Short labels for compact display contexts (e.g. TaskCard tags).
 * Falls back to STEP_LABELS for steps not explicitly shortened.
 */
export const STEP_LABELS_SHORT: Record<string, string> = {
  ...STEP_LABELS,
  pre_namd: 'PRE',
}

/**
 * Phase ordering for job sorting (lower = earlier in workflow).
 * Used by TaskDetailPage to sort jobs within a task.
 */
export const PHASE_ORDER: Record<string, number> = {
  nvt: 0,
  nve: 1,
  scf: 2,
  [FUSED_SCF_PRENAMD]: 2,
  fused_cat: 2,
  pre_namd: 3,
  namd: 4,
}
