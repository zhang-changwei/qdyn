<template>
  <el-steps
    :active="activeStepIndex"
    align-center
    finish-status="success"
    process-status="process"
  >
    <el-step
      v-for="step in workflowSteps"
      :key="step.value"
      :title="step.label"
      :description="getStepDescription(step.value)"
      :status="getStepStatus(step.value)"
    />
  </el-steps>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { JobStatusItem, DerivedState } from '@/api/types'
import { FUSED_SCF_PRENAMD } from '@/constants/steps'

const props = defineProps<{
  jobs: JobStatusItem[]
}>()

interface StepConfig {
  value: string
  label: string
}

const workflowSteps = computed<StepConfig[]>(() => {
  const hasFused = props.jobs.some(j => {
    const n = j.name.toLowerCase()
    return n.includes('fused') || n.includes('cat_canac')
  })
  if (hasFused) {
    return [
      { value: 'nvt', label: 'NVT' },
      { value: 'nve', label: 'NVE' },
      { value: FUSED_SCF_PRENAMD, label: 'Fused SCF+Pre-NAMD' },
      { value: 'namd', label: 'NAMD' },
    ]
  }
  return [
    { value: 'nvt', label: 'NVT' },
    { value: 'nve', label: 'NVE' },
    { value: 'scf', label: 'SCF' },
    { value: 'pre_namd', label: 'Pre-NAMD' },
    { value: 'namd', label: 'NAMD' },
  ]
})

const STATE_PRIORITY: Record<string, number> = {
  FAILED: 0, ERROR: 0, CANCELLED: 0, STOPPED: 0,
  PAUSED: 1,
  RUNNING: 2,
  QUEUED: 3, DISPATCHING: 3, PENDING: 3, WAITING: 3, READY: 3,
  COMPLETED: 4,
}

function worstState(a: DerivedState | null, b: DerivedState): DerivedState {
  if (a === null) return b
  return (STATE_PRIORITY[a] ?? 99) <= (STATE_PRIORITY[b] ?? 99) ? a : b
}

const jobStatusMap = computed((): Record<string, DerivedState | null> => {
  const map: Record<string, DerivedState | null> = {}
  for (const job of props.jobs) {
    const stepName = extractStepName(job.name)
    if (stepName && job.derived_state) {
      map[stepName] = worstState(map[stepName] ?? null, job.derived_state)
    }
  }
  return map
})

function extractStepName(jobName: string): string | null {
  const n = jobName.toLowerCase()
  // Fused priority match (before scf/namd substring would match)
  if (n.includes('fused') || n.includes('cat_canac')) return FUSED_SCF_PRENAMD
  for (const step of workflowSteps.value) {
    if (n.includes(step.value)) {
      return step.value
    }
  }
  return null
}

function getStepStatus(stepValue: string): '' | 'wait' | 'process' | 'success' | 'error' | 'finish' {
  const state = jobStatusMap.value[stepValue]
  if (!state) return 'wait'

  switch (state) {
    case 'COMPLETED':
      return 'success'
    case 'FAILED':
    case 'ERROR':
    case 'CANCELLED':
    case 'STOPPED':
      return 'error'
    case 'RUNNING':
      return 'process'
    case 'PAUSED':
      return 'wait'
    case 'PENDING':
    case 'QUEUED':
    case 'DISPATCHING':
    default:
      return 'wait'
  }
}

function getStepDescription(stepValue: string): string {
  const state = jobStatusMap.value[stepValue]
  if (!state) return 'Not started'

  switch (state) {
    case 'COMPLETED':
      return 'Done'
    case 'FAILED':
      return 'Failed'
    case 'ERROR':
      return 'Error'
    case 'RUNNING':
      return 'In progress'
    case 'PAUSED':
      return 'Paused'
    case 'STOPPED':
      return 'Stopped'
    case 'CANCELLED':
      return 'Cancelled'
    case 'PENDING':
    case 'QUEUED':
    case 'DISPATCHING':
      return 'Waiting'
    default:
      return 'Unknown'
  }
}

const activeStepIndex = computed((): number => {
  for (let i = 0; i < workflowSteps.value.length; i++) {
    const state = jobStatusMap.value[workflowSteps.value[i].value]
    if (!state || state === 'PENDING') {
      return i
    }
    if (state === 'RUNNING') {
      return i
    }
  }
  return workflowSteps.value.length
})
</script>

<style scoped>
/* --- Step icon overrides --- */

/* Completed (finish/success) step icon */
:deep(.el-step__head.is-success .el-step__icon) {
  background-color: var(--success-fg);
  border-color: var(--success-fg);
  color: #fff;
}

/* Running (process) step icon — phosphor with pulse */
:deep(.el-step__head.is-process .el-step__icon) {
  background-color: var(--phosphor);
  border-color: var(--phosphor);
  color: #fff;
  animation: qdyn-phosphor-pulse 1.6s ease-in-out infinite;
}

/* Pending (wait) step icon */
:deep(.el-step__head.is-wait .el-step__icon) {
  background-color: var(--ink-300);
  border-color: var(--ink-300);
  color: #fff;
}

/* Error step icon */
:deep(.el-step__head.is-error .el-step__icon) {
  background-color: var(--danger-fg);
  border-color: var(--danger-fg);
  color: #fff;
}

/* --- Step title & description --- */

:deep(.el-step__title) {
  font: var(--text-body-strong);
}

:deep(.el-step__description) {
  font-size: var(--fs-12);
  color: var(--fg-tertiary);
}

/* Override Element Plus description color overrides per status */
:deep(.el-step__description.is-success) {
  color: var(--success-fg);
}

:deep(.el-step__description.is-process) {
  color: var(--phosphor-strong);
}

:deep(.el-step__description.is-wait) {
  color: var(--fg-tertiary);
}

:deep(.el-step__description.is-error) {
  color: var(--danger-fg);
}

/* --- Connector line overrides --- */

/* Base connector line (always visible as subtle gray) */
:deep(.el-step__line) {
  background-color: var(--border-default) !important;
}

/* Completed connector: fill overlays base */
:deep(.el-step__head.is-success .el-step__line-inner) {
  border-color: var(--success-fg) !important;
  background-color: var(--success-fg) !important;
}

/* Process connector: phosphor fill */
:deep(.el-step__head.is-process .el-step__line-inner) {
  border-color: var(--phosphor) !important;
  background-color: var(--phosphor) !important;
}

/* Wait / error connectors: no fill, base line shows through */
:deep(.el-step__head.is-wait .el-step__line-inner),
:deep(.el-step__head.is-error .el-step__line-inner) {
  border-color: transparent !important;
  background-color: transparent !important;
}
</style>
