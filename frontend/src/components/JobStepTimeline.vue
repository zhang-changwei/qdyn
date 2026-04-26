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
      { value: 'fused_scf_prenamd', label: 'Fused SCF+Pre-NAMD' },
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
  if (n.includes('fused') || n.includes('cat_canac')) return 'fused_scf_prenamd'
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
