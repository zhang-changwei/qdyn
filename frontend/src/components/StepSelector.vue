<template>
  <div class="step-selector">
    <el-checkbox-group
      :model-value="modelValue"
      @update:model-value="handleUpdate"
    >
      <div class="step-list">
        <div
          v-for="(step, index) in availableSteps"
          :key="step.value"
          class="step-item"
          :class="{ 'step-done': isCompletedStep(step.value) }"
        >
          <el-checkbox
            :value="step.value"
            :disabled="!isStepSelectable(step.value)"
          >
            <span class="step-label-text">{{ step.label }}</span>
            <el-icon v-if="isCompletedStep(step.value)" class="done-icon"><Check /></el-icon>
          </el-checkbox>
          <el-icon
            v-if="index < availableSteps.length - 1"
            class="step-arrow"
            :class="{ active: isArrowActive(step.value) }"
          >
            <ArrowRight />
          </el-icon>
        </div>
      </div>
    </el-checkbox-group>

    <div class="step-hint">
      <el-text type="info" size="small">
        <span v-if="resume && completedSteps && completedSteps.length > 0">
          Resume mode: Continue from the next step after completed steps.
        </span>
        <span v-else-if="resume">
          Resume mode: Select contiguous steps to run.
        </span>
        <span v-else>Select contiguous steps starting from NVT or SCF (e.g. nvt + nve + scf, or scf + pre_namd + namd).</span>
      </el-text>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight, Check } from '@element-plus/icons-vue'

const props = withDefaults(defineProps<{
  modelValue: string[]
  resume?: boolean
  completedSteps?: string[]
}>(), {
  resume: false,
  completedSteps: () => []
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

interface StepConfig {
  value: string
  label: string
}

const availableSteps: StepConfig[] = [
  { value: 'nvt', label: 'NVT' },
  { value: 'nve', label: 'NVE' },
  { value: 'scf', label: 'SCF' },
  { value: 'pre_namd', label: 'Pre-NAMD' },
  { value: 'namd', label: 'NAMD' }
]

const stepOrder = computed((): string[] => {
  return availableSteps.map(s => s.value)
})

/** Index of the first selectable step in resume mode */
const resumeStartIndex = computed((): number => {
  if (!props.resume || !props.completedSteps || props.completedSteps.length === 0) {
    return 0
  }
  const lastCompleted = props.completedSteps[props.completedSteps.length - 1]
  const idx = stepOrder.value.indexOf(lastCompleted)
  return idx >= 0 ? idx + 1 : 0
})

function isCompletedStep(step: string): boolean {
  return props.resume && (props.completedSteps ?? []).includes(step)
}

function isStepSelectable(step: string): boolean {
  const stepIndex = stepOrder.value.indexOf(step)

  // Resume mode with known completed steps
  if (props.resume && props.completedSteps && props.completedSteps.length > 0) {
    // Completed steps are always disabled (shown as done)
    if (stepIndex < resumeStartIndex.value) return false

    // First selectable step is always allowed
    if (stepIndex === resumeStartIndex.value) return true

    // Already selected — allow unchecking
    if (props.modelValue.includes(step)) return true

    // Allow if the previous step in order is selected
    const prevStep = stepOrder.value[stepIndex - 1]
    return props.modelValue.includes(prevStep)
  }

  // Resume mode without completed steps: only allow starting from nvt
  if (props.resume) {
    const allowedFirstSteps = ['nvt']
    if (props.modelValue.length === 0) {
      return allowedFirstSteps.includes(step)
    }
    if (props.modelValue.includes(step)) return true
    const selectedIndices = props.modelValue.map(s => stepOrder.value.indexOf(s)).sort((a, b) => a - b)
    return stepIndex === selectedIndices[selectedIndices.length - 1] + 1
  }

  // Normal (new task) mode — allow starting from nvt or scf
  const allowedFirstSteps = ['nvt', 'scf']
  if (props.modelValue.length === 0) {
    return allowedFirstSteps.includes(step)
  }

  // Already selected — always allow unchecking
  if (props.modelValue.includes(step)) {
    return true
  }

  // Determine the current contiguous range boundaries
  const selectedIndices = props.modelValue.map(s => stepOrder.value.indexOf(s)).sort((a, b) => a - b)
  const minIdx = selectedIndices[0]
  const maxIdx = selectedIndices[selectedIndices.length - 1]

  // Allow extending one step after the current range
  if (stepIndex === maxIdx + 1) {
    return true
  }

  // Allow extending one step before the current range (but not below allowed first steps)
  if (stepIndex === minIdx - 1 && allowedFirstSteps.includes(step)) {
    return true
  }

  return false
}

function isArrowActive(step: string): boolean {
  if (isCompletedStep(step)) return true
  return props.modelValue.includes(step)
}

function handleUpdate(newValue: string[]): void {
  // Filter out completed steps — they should never appear in modelValue
  const filtered = newValue.filter(s => !isCompletedStep(s))
  const sortedValue = sortSteps(filtered)

  // Auto-trim: deselecting a step removes all subsequent steps
  if (sortedValue.length < props.modelValue.length) {
    const removedSteps = props.modelValue.filter(s => !sortedValue.includes(s))
    if (removedSteps.length > 0) {
      let minRemovedIndex = stepOrder.value.length
      for (const removed of removedSteps) {
        const idx = stepOrder.value.indexOf(removed)
        if (idx < minRemovedIndex) {
          minRemovedIndex = idx
        }
      }
      const trimmed = sortedValue.filter(
        s => stepOrder.value.indexOf(s) < minRemovedIndex
      )
      emit('update:modelValue', trimmed)
      return
    }
  }

  emit('update:modelValue', sortedValue)
}

function sortSteps(steps: string[]): string[] {
  return [...steps].sort((a, b) => {
    return stepOrder.value.indexOf(a) - stepOrder.value.indexOf(b)
  })
}
</script>

<style scoped>
.step-selector {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.step-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.step-item.step-done :deep(.el-checkbox) {
  opacity: 0.6;
}

.step-item.step-done :deep(.el-checkbox__label) {
  color: var(--el-color-success);
}

.step-label-text {
  font-weight: 500;
}

.done-icon {
  font-size: 12px;
  color: var(--el-color-success);
  margin-left: 2px;
}

.step-arrow {
  color: var(--el-text-color-placeholder);
  transition: color 0.3s ease;
}

.step-arrow.active {
  color: var(--el-color-primary);
}

.step-hint {
  margin-top: 8px;
}
</style>
