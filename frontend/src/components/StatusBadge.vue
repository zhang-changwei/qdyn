<template>
  <el-tag :type="tagType" :effect="effect" size="small">
    {{ displayText }}
  </el-tag>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DerivedState } from '@/api/types'

const props = defineProps<{
  status: DerivedState | null | undefined
}>()

interface StatusConfig {
  type: '' | 'success' | 'warning' | 'danger' | 'info'
  effect: 'light' | 'dark' | 'plain'
  text: string
}

const STATUS_CONFIG: Record<DerivedState, StatusConfig> = {
  RUNNING: { type: 'warning', effect: 'light', text: 'Running' },
  COMPLETED: { type: 'success', effect: 'light', text: 'Completed' },
  FAILED: { type: 'danger', effect: 'light', text: 'Failed' },
  PENDING: { type: 'info', effect: 'light', text: 'Pending' },
  PAUSED: { type: 'warning', effect: 'light', text: 'Paused' },
  ERROR: { type: 'danger', effect: 'dark', text: 'Error' }
}

const DEFAULT_CONFIG: StatusConfig = {
  type: 'info',
  effect: 'plain',
  text: 'Unknown'
}

const currentConfig = computed((): StatusConfig => {
  if (!props.status) return DEFAULT_CONFIG
  return STATUS_CONFIG[props.status] || DEFAULT_CONFIG
})

const tagType = computed(() => currentConfig.value.type)
const effect = computed(() => currentConfig.value.effect)
const displayText = computed(() => currentConfig.value.text)
</script>
