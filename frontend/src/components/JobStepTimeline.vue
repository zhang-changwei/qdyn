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

const workflowSteps: StepConfig[] = [
  { value: 'nvt', label: 'NVT' },
  { value: 'nve', label: 'NVE' },
  { value: 'scf', label: 'SCF' },
  { value: 'pre_namd', label: 'Pre-NAMD' },
  { value: 'namd', label: 'NAMD' }
]

const jobStatusMap = computed((): Record<string, DerivedState | null> => {
  const map: Record<string, DerivedState | null> = {}
  for (const job of props.jobs) {
    const stepName = extractStepName(job.name)
    if (stepName && !map[stepName]) {
      map[stepName] = job.derived_state
    }
  }
  return map
})

function extractStepName(jobName: string): string | null {
  const normalizedName = jobName.toLowerCase()
  for (const step of workflowSteps) {
    if (normalizedName.includes(step.value)) {
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
      return 'error'
    case 'RUNNING':
      return 'process'
    case 'PAUSED':
      return 'wait'
    case 'PENDING':
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
    case 'PENDING':
      return 'Waiting'
    default:
      return 'Unknown'
  }
}

const activeStepIndex = computed((): number => {
  for (let i = 0; i < workflowSteps.length; i++) {
    const state = jobStatusMap.value[workflowSteps[i].value]
    if (!state || state === 'PENDING') {
      return i
    }
    if (state === 'RUNNING') {
      return i
    }
  }
  return workflowSteps.length
})
</script>
