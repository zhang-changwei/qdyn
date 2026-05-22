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

    <!-- Fuse toggle -->
    <div v-if="showFuseToggle" class="fuse-toggle">
      <el-switch
        :model-value="isFused"
        :disabled="fuseToggleDisabled"
        active-text="Fuse SCF + Pre-NAMD"
        @update:model-value="handleFuseToggle"
      />
      <el-text v-if="fuseToggleDisabled" type="info" size="small" class="fuse-hint">
        Locked by completed steps
      </el-text>
    </div>

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
import { FUSED_SCF_PRENAMD } from '@/constants/steps'

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

const STEPS_NORMAL: StepConfig[] = [
  { value: 'nvt', label: 'NVT' },
  { value: 'nve', label: 'NVE' },
  { value: 'scf', label: 'SCF' },
  { value: 'pre_namd', label: 'Pre-NAMD' },
  { value: 'namd', label: 'NAMD' },
]

const STEPS_FUSED: StepConfig[] = [
  { value: 'nvt', label: 'NVT' },
  { value: 'nve', label: 'NVE' },
  { value: FUSED_SCF_PRENAMD, label: 'Fused SCF+Pre-NAMD' },
  { value: 'namd', label: 'NAMD' },
]

const isFused = computed((): boolean => {
  return props.modelValue.includes(FUSED_SCF_PRENAMD)
    || props.completedSteps.includes(FUSED_SCF_PRENAMD)
})

const effectiveStepOrder = computed((): string[] => {
  if (isFused.value) {
    return STEPS_FUSED.map(s => s.value)
  }
  return STEPS_NORMAL.map(s => s.value)
})

const availableSteps = computed((): StepConfig[] => {
  return isFused.value ? STEPS_FUSED : STEPS_NORMAL
})

const showFuseToggle = computed((): boolean => {
  const hasScfAndPreNamd = props.modelValue.includes('scf') && props.modelValue.includes('pre_namd')
  const hasFused = props.modelValue.includes(FUSED_SCF_PRENAMD)
  const completedFused = props.completedSteps.includes(FUSED_SCF_PRENAMD)
  const completedScf = props.completedSteps.includes('scf')
  return hasScfAndPreNamd || hasFused || completedFused || completedScf
})

const fuseToggleDisabled = computed((): boolean => {
  if (!props.resume) return false
  // completedSteps contains fused → locked on
  if (props.completedSteps.includes(FUSED_SCF_PRENAMD)) return true
  // completedSteps contains scf (independent) → locked off
  if (props.completedSteps.includes('scf')) return true
  return false
})

const stepOrder = computed((): string[] => effectiveStepOrder.value)

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
    if (stepIndex < resumeStartIndex.value) return false
    if (stepIndex === resumeStartIndex.value) return true
    if (props.modelValue.includes(step)) return true
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

  // Normal (new task) mode — allow starting from nvt, scf, or fused_scf_prenamd
  const allowedFirstSteps = ['nvt', 'scf', FUSED_SCF_PRENAMD]
  if (props.modelValue.length === 0) {
    return allowedFirstSteps.includes(step)
  }

  if (props.modelValue.includes(step)) {
    return true
  }

  const selectedIndices = props.modelValue.map(s => stepOrder.value.indexOf(s)).sort((a, b) => a - b)
  const minIdx = selectedIndices[0]
  const maxIdx = selectedIndices[selectedIndices.length - 1]

  if (stepIndex === maxIdx + 1) {
    return true
  }

  if (stepIndex === minIdx - 1 && allowedFirstSteps.includes(step)) {
    return true
  }

  return false
}

function isArrowActive(step: string): boolean {
  if (isCompletedStep(step)) return true
  return props.modelValue.includes(step)
}

function handleFuseToggle(fused: boolean): void {
  let newSteps: string[]
  const targetOrder = fused
    ? STEPS_FUSED.map(s => s.value)
    : STEPS_NORMAL.map(s => s.value)
  if (fused) {
    newSteps = props.modelValue
      .filter(s => s !== 'scf' && s !== 'pre_namd')
      .concat(FUSED_SCF_PRENAMD)
  } else {
    newSteps = props.modelValue
      .filter(s => s !== FUSED_SCF_PRENAMD)
      .concat('scf', 'pre_namd')
  }
  emit('update:modelValue', [...newSteps].sort((a, b) =>
    targetOrder.indexOf(a) - targetOrder.indexOf(b)
  ))
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
  gap: var(--space-3);
}

.step-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}

.step-item {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.step-item.step-done :deep(.el-checkbox) {
  opacity: 0.6;
}

.step-item.step-done :deep(.el-checkbox__label) {
  color: var(--success-fg);
}

.step-label-text {
  font: var(--text-body-strong);
}

.done-icon {
  font-size: var(--fs-12);
  color: var(--success-fg);
  margin-left: 2px;
}

.step-arrow {
  color: var(--fg-placeholder);
  transition: color var(--dur-base) var(--ease-standard);
}

.step-arrow.active {
  color: var(--brand-primary);
}

.fuse-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) 0;
}

.fuse-hint {
  font-style: italic;
}

.step-hint {
  margin-top: var(--space-2);
}

.step-hint :deep(.el-text) {
  font-size: var(--fs-12);
  color: var(--fg-tertiary);
}
</style>
