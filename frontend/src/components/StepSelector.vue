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
        >
          <el-checkbox
            :label="step.value"
            :disabled="!isStepSelectable(step.value)"
          >
            <span class="step-label">{{ step.label }}</span>
          </el-checkbox>
          <el-icon
            v-if="index < availableSteps.length - 1"
            class="step-arrow"
            :class="{ active: isPreviousStepSelected(step.value) }"
          >
            <ArrowRight />
          </el-icon>
        </div>
      </div>
    </el-checkbox-group>

    <div class="step-hint">
      <el-text type="info" size="small">
        Steps must be selected in order: nvt, nvt + nve, nvt + nve + scf, etc.
      </el-text>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight } from '@element-plus/icons-vue'

const props = defineProps<{
  modelValue: string[]
}>()

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

function isStepSelectable(step: string): boolean {
  if (props.modelValue.length === 0) {
    return step === 'nvt'
  }

  if (props.modelValue.includes(step)) {
    return true
  }

  const stepIndex = stepOrder.value.indexOf(step)
  if (stepIndex === 0) {
    return true
  }

  const previousStep = stepOrder.value[stepIndex - 1]
  return props.modelValue.includes(previousStep)
}

function isPreviousStepSelected(step: string): boolean {
  const stepIndex = stepOrder.value.indexOf(step)
  if (stepIndex === 0) return false
  const previousStep = stepOrder.value[stepIndex - 1]
  return props.modelValue.includes(previousStep)
}

function handleUpdate(newValue: string[]): void {
  const sortedValue = sortSteps(newValue)
  emit('update:modelValue', sortedValue)
}

function sortSteps(steps: string[]): string[] {
  return steps.sort((a, b) => {
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

.step-label {
  font-weight: 500;
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
