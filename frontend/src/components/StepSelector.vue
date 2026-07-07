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
          :class="{
            'step-done': isCompletedStep(step.value),
            'step-locked': isLockedCompletedStep(step.value),
          }"
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
        <span v-else>Select contiguous steps starting from NVT, NVE, or SCF (e.g. nvt + nve + scf, nve + scf, or scf + pre_namd + namd).</span>
      </el-text>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, Check } from '@element-plus/icons-vue'
import { FUSED_SCF_PRENAMD } from '@/constants/steps'

const props = withDefaults(defineProps<{
  modelValue: string[]
  resume?: boolean
  completedSteps?: string[]
  resumeEarliestStep?: string | null
}>(), {
  resume: false,
  completedSteps: () => [],
  resumeEarliestStep: null
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

const fuseModeOverride = ref<boolean | null>(null)

watch(
  () => [props.completedSteps.join('|'), props.resumeEarliestStep ?? ''],
  () => {
    fuseModeOverride.value = null
  }
)

const isFused = computed((): boolean => {
  if (fuseModeOverride.value !== null) {
    return fuseModeOverride.value
  }
  if (props.modelValue.includes(FUSED_SCF_PRENAMD)) {
    return true
  }
  if (props.modelValue.includes('scf') || props.modelValue.includes('pre_namd')) {
    return false
  }
  return props.completedSteps.includes(FUSED_SCF_PRENAMD)
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
  return props.completedSteps.some(step => {
    return (step === 'scf' || step === FUSED_SCF_PRENAMD)
      && isLockedCompletedStep(step)
  })
})

const stepOrder = computed((): string[] => effectiveStepOrder.value)

const resumeStartIndex = computed((): number => {
  if (!props.resume) {
    return 0
  }

  if (props.resumeEarliestStep) {
    const earliestIdx = stepOrder.value.indexOf(props.resumeEarliestStep)
    if (earliestIdx >= 0) {
      return earliestIdx
    }
  }

  if (!props.completedSteps || props.completedSteps.length === 0) {
    return 0
  }

  const lastCompleted = props.completedSteps[props.completedSteps.length - 1]
  const idx = stepOrder.value.indexOf(lastCompleted)
  return idx >= 0 ? idx + 1 : 0
})

const maxValidStartIndex = computed((): number => {
  if (!props.resume || !props.completedSteps?.length) {
    return stepOrder.value.length - 1
  }

  const completedIndices = props.completedSteps
    .map(s => stepOrder.value.indexOf(s))
    .filter(idx => idx >= 0)
  if (completedIndices.length === 0) {
    return stepOrder.value.length - 1
  }

  const lastCompletedIdx = Math.max(...completedIndices)
  return Math.min(lastCompletedIdx + 1, stepOrder.value.length - 1)
})

function isParentCompletedStep(step: string): boolean {
  return props.resume && (props.completedSteps ?? []).includes(step)
}

function isLockedCompletedStep(step: string): boolean {
  if (!isParentCompletedStep(step)) return false
  const stepIndex = stepOrder.value.indexOf(step)
  return stepIndex >= 0 && stepIndex < resumeStartIndex.value
}

function isCompletedStep(step: string): boolean {
  // Show the green check for every step in completedSteps, regardless of
  // whether it sits before or after the resume start point. The selectable
  // rules (isStepSelectable) and submission filtering (handleUpdate) are
  // governed separately by isLockedCompletedStep, so this display-only flag
  // does not alter resume semantics.
  if (isParentCompletedStep(step)) return true
  return isLockedCompletedStep(step)
}

function isStepSelectable(step: string): boolean {
  const stepIndex = stepOrder.value.indexOf(step)
  if (stepIndex < 0) return false

  // Resume mode with known completed steps
  if (props.resume && props.completedSteps && props.completedSteps.length > 0) {
    if (stepIndex < resumeStartIndex.value) return false
    if (props.modelValue.length === 0) {
      return stepIndex <= maxValidStartIndex.value
    }
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

  // Normal (new task) mode — allow starting from nvt, nve, scf, or fused_scf_prenamd.
  // NVE-first is valid: the backend contiguity rule already permits any
  // contiguous suffix start, and NVE-first reads the uploaded single-frame
  // structure via the POSCAR path.
  const allowedFirstSteps = ['nvt', 'nve', 'scf', FUSED_SCF_PRENAMD]
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
  if (fuseToggleDisabled.value) return
  fuseModeOverride.value = fused
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
  emit('update:modelValue', normalizeResumeSelection(newSteps, targetOrder))
}

function handleUpdate(newValue: string[]): void {
  // Locked parent-completed steps are inherited context, not steps to submit.
  const filtered = uniqueSteps(newValue).filter(s => !isLockedCompletedStep(s))
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




function normalizeResumeSelection(steps: string[], order: string[] = stepOrder.value): string[] {
  const sorted = sortSteps(
    uniqueSteps(steps).filter(s => {
      const idx = order.indexOf(s)
      return idx >= resumeStartIndex.value
    }),
    order,
  )
  if (sorted.length <= 1) return sorted
  const indices = sorted.map(s => order.indexOf(s))
  for (let i = 1; i < indices.length; i++) {
    if (indices[i] !== indices[i - 1] + 1) return sorted.slice(0, i)
  }
  return sorted
}

function uniqueSteps(steps: string[]): string[] {
  return [...new Set(steps)]
}

function sortSteps(steps: string[], order: string[] = stepOrder.value): string[] {
  return [...steps].sort((a, b) => {
    return order.indexOf(a) - order.indexOf(b)
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

.step-item.step-done :deep(.el-checkbox__label) {
  color: var(--success-fg);
}

/* Locked completed steps (before resume start point, not selectable) are
   dimmed to signal they are inherited context, not actionable. Completed-but-
   selectable steps keep full opacity so they read as interactive. */
.step-item.step-locked :deep(.el-checkbox) {
  opacity: 0.6;
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
