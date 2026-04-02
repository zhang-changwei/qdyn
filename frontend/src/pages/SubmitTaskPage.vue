<template>
  <div class="submit-task-page">
    <!-- Header -->
    <div class="page-header">
      <el-button @click="goBack">
        <el-icon><ArrowLeft /></el-icon>
        Back
      </el-button>
      <h2 class="page-title">{{ submitMode === 'resume' ? 'Resume Task' : 'Submit New Task' }}</h2>
    </div>

    <!-- Mode switch -->
    <el-card class="form-section mode-section">
      <el-radio-group v-model="submitMode" @change="handleModeChange">
        <el-radio-button value="new">New Task</el-radio-button>
        <el-radio-button value="resume">Resume Task</el-radio-button>
      </el-radio-group>
    </el-card>

    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-position="top"
      class="submit-form"
    >
      <!-- POSCAR upload section (new mode only) -->
      <el-card v-if="submitMode === 'new'" class="form-section">
        <template #header>
          <span class="section-title">1. Structure (POSCAR)</span>
        </template>
        <PoscarUploader
          @file-loaded="handlePoscarLoaded"
          @clear="handlePoscarCleared"
        />
        <el-alert
          v-if="poscarValidation"
          :title="poscarValidation.valid ? 'Structure valid' : 'Validation failed'"
          :type="poscarValidation.valid ? 'success' : 'error'"
          :description="poscarValidation.valid
            ? `${poscarValidation.structure?.formula} (${poscarValidation.structure?.num_atoms} atoms)`
            : poscarValidation.error"
          show-icon
          class="validation-alert"
        />
      </el-card>

      <!-- Resume task selector (resume mode only) -->
      <el-card v-if="submitMode === 'resume'" class="form-section">
        <template #header>
          <span class="section-title">1. Select Previous Task</span>
        </template>
        <el-alert
          title="Structure will be inherited from the selected task"
          type="info"
          show-icon
          :closable="false"
          class="resume-info-alert"
        />
        <ResumeTaskSelector
          v-model="selectedResumeTaskId"
          :tasks="resumeTasks"
          :loading="resumeTasksLoading"
          @task-selected="handleResumeTaskSelected"
        />
      </el-card>

      <!-- Step selection section -->
      <el-card class="form-section">
        <template #header>
          <span class="section-title">2. Workflow Steps</span>
        </template>
        <el-form-item prop="steps">
          <StepSelector
            v-model="formData.steps"
            :resume="submitMode === 'resume'"
            :completed-steps="selectedResumeTask?.completed_steps"
          />
        </el-form-item>
      </el-card>

      <!-- Method & Basic Settings section -->
      <el-card class="form-section">
        <template #header>
          <span class="section-title">3. Method & Settings</span>
        </template>
        <el-row :gutter="16">
          <el-col :span="24">
            <el-form-item label="NAMD Method">
              <el-radio-group v-model="formData.method">
                <el-radio value="namd">NAMD (Standard)</el-radio>
                <el-tooltip
                  content="Not yet supported, coming soon"
                  placement="top"
                >
                  <span class="disabled-radio-wrapper">
                    <el-radio value="n2amd" disabled>N2AMD</el-radio>
                  </span>
                </el-tooltip>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="DFT Software">
              <el-select v-model="formData.basic_input.software" style="width: 100%;">
                <el-option label="VASP" value="vasp" />
                <el-option label="CP2K" value="cp2k" disabled>
                  <span>CP2K <el-tag size="small" type="info" style="margin-left: 8px;">Coming soon</el-tag></span>
                </el-option>
                <el-option label="SIESTA" value="siesta" disabled>
                  <span>SIESTA <el-tag size="small" type="info" style="margin-left: 8px;">Coming soon</el-tag></span>
                </el-option>
                <el-option label="ABACUS" value="abacus" disabled>
                  <span>ABACUS <el-tag size="small" type="info" style="margin-left: 8px;">Coming soon</el-tag></span>
                </el-option>
                <el-option label="OpenMX" value="openmx" disabled>
                  <span>OpenMX <el-tag size="small" type="info" style="margin-left: 8px;">Coming soon</el-tag></span>
                </el-option>
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item>
              <template #label>
                <span>
                  Generate Plots
                  <el-tooltip
                    content="Generate matplotlib result plots after calculation completes"
                    placement="top"
                    :show-after="300"
                  >
                    <el-icon class="param-help-icon"><QuestionFilled /></el-icon>
                  </el-tooltip>
                </span>
              </template>
              <el-switch v-model="formData.basic_input.plot" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-card>

      <!-- Parameter configuration section (dynamic forms) -->
      <el-card v-if="formData.steps.length > 0" class="form-section">
        <template #header>
          <span class="section-title">4. Step Parameters</span>
        </template>

        <template v-if="schemas">
          <template v-for="(step, idx) in formData.steps" :key="step">
            <el-divider v-if="idx > 0" />
            <div class="step-params">
              <h4 class="step-params-title">{{ STEP_CONFIG[step].label }}</h4>
              <DynamicStepForm
                :schema="schemas[STEP_CONFIG[step].schemaKey]"
                :model-value="formData[STEP_CONFIG[step].inputKey] as Record<string, unknown>"
                @update:model-value="formData[STEP_CONFIG[step].inputKey] = $event as any"
              />
            </div>
          </template>
        </template>

        <el-skeleton v-else :rows="3" animated />
      </el-card>

      <!-- Submit section -->
      <div class="submit-section">
        <el-button
          type="primary"
          size="large"
          :loading="submitting"
          @click="handleSubmit"
        >
          {{ submitMode === 'resume' ? 'Resume Task' : 'Submit Task' }}
        </el-button>
      </div>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, QuestionFilled } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import PoscarUploader from '@/components/PoscarUploader.vue'
import StepSelector from '@/components/StepSelector.vue'
import ResumeTaskSelector from '@/components/ResumeTaskSelector.vue'
import DynamicStepForm from '@/components/DynamicStepForm.vue'
import { validatePoscar } from '@/api/structures'
import { getStepInputSchemas, type StepInputSchemas } from '@/api/schema'
import { getTaskSummaryList } from '@/api/tasks'
import { buildDefaultsFromSchema } from '@/utils/schema-form'
import http from '@/api/http'
import type { ValidatePoscarResponse, TaskSummary, NVTInput, NVEInput, SCFInput, PreNAMDInput, NAMDInput } from '@/api/types'

// Step configuration: maps step name to formData key and schema key
const STEP_CONFIG: Record<string, {
  inputKey: keyof typeof formData
  schemaKey: keyof StepInputSchemas
  label: string
}> = {
  nvt: { inputKey: 'nvt_input', schemaKey: 'nvt', label: 'NVT Parameters' },
  nve: { inputKey: 'nve_input', schemaKey: 'nve', label: 'NVE Parameters' },
  scf: { inputKey: 'scf_input', schemaKey: 'scf', label: 'SCF Parameters' },
  pre_namd: { inputKey: 'prenamd_input', schemaKey: 'pre_namd', label: 'Pre-NAMD Parameters' },
  namd: { inputKey: 'namd_input', schemaKey: 'namd', label: 'NAMD Parameters' },
}

const router = useRouter()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const poscarContent = ref('')
const poscarValidation = ref<ValidatePoscarResponse | null>(null)
const poscarVersion = ref(0) // Used to prevent race condition in validation
const schemas = ref<StepInputSchemas | null>(null)

// Resume mode state
const submitMode = ref<'new' | 'resume'>('new')
const resumeTasks = ref<TaskSummary[]>([])
const resumeTasksLoading = ref(false)
const selectedResumeTaskId = ref<string | null>(null)
const selectedResumeTask = ref<TaskSummary | null>(null)

onMounted(async () => {
  try {
    schemas.value = await getStepInputSchemas()
    // Backfill defaults for any steps already selected before schema loaded
    for (const step of formData.steps) {
      const config = STEP_CONFIG[step]
      if (!config) continue
      const current = formData[config.inputKey]
      if (!current || Object.keys(current as object).length === 0) {
        ;(formData as Record<string, unknown>)[config.inputKey] = buildStepDefaults(config.schemaKey)
      }
    }
  } catch (error) {
    ElMessage.error('Failed to load form schemas')
  }
})

/**
 * Build defaults for a step from its schema.
 * Falls back to an empty object if schemas are not loaded yet.
 */
function buildStepDefaults(schemaKey: keyof StepInputSchemas): Record<string, unknown> {
  if (!schemas.value) return {}
  return buildDefaultsFromSchema(schemas.value[schemaKey])
}

const formData = reactive<{
  steps: string[]
  method: 'namd' | 'n2amd'
  basic_input: { software: string; plot: boolean }
  nvt_input: NVTInput | Record<string, unknown>
  nve_input: NVEInput | Record<string, unknown>
  scf_input: SCFInput | Record<string, unknown>
  prenamd_input: PreNAMDInput | Record<string, unknown>
  namd_input: NAMDInput | Record<string, unknown>
}>({
  steps: [],
  method: 'namd',
  basic_input: { software: 'vasp', plot: false },
  nvt_input: {},
  nve_input: {},
  scf_input: {},
  prenamd_input: {},
  namd_input: {},
})

const formRules: FormRules = {
  steps: [
    {
      validator: (_rule, value, callback) => {
        if (!value || value.length === 0) {
          callback(new Error('At least one step must be selected'))
        } else {
          callback()
        }
      },
      trigger: 'change'
    }
  ]
}

// Watch steps changes to init/reset input objects from schema defaults
watch(
  () => formData.steps,
  (newSteps, oldSteps) => {
    // Initialize inputs for newly selected steps
    for (const step of newSteps) {
      const config = STEP_CONFIG[step]
      if (!config) continue
      const current = formData[config.inputKey]
      if (!current || Object.keys(current as object).length === 0) {
        ;(formData as Record<string, unknown>)[config.inputKey] = buildStepDefaults(config.schemaKey)
      }
    }

    // Reset inputs for deselected steps
    const removedSteps = (oldSteps || []).filter(s => !newSteps.includes(s))
    for (const step of removedSteps) {
      const config = STEP_CONFIG[step]
      if (!config) continue
      ;(formData as Record<string, unknown>)[config.inputKey] = buildStepDefaults(config.schemaKey)
    }
  },
  { deep: true }
)

async function handlePoscarLoaded(content: string): Promise<void> {
  poscarContent.value = content
  poscarVersion.value++ // Increment version to track this request
  const currentVersion = poscarVersion.value
  poscarValidation.value = null

  try {
    const result = await validatePoscar(content)
    // Only update validation if this is the latest request
    if (poscarVersion.value === currentVersion) {
      poscarValidation.value = result
    }
  } catch (error) {
    // Only update error if this is the latest request
    if (poscarVersion.value === currentVersion) {
      poscarValidation.value = {
        valid: false,
        error: error instanceof Error ? error.message : 'Validation failed'
      }
    }
  }
}

function handlePoscarCleared(): void {
  poscarContent.value = ''
  poscarValidation.value = null
  poscarVersion.value++ // Increment version to invalidate pending validations
}

function goBack(): void {
  router.push({ name: 'task-list' })
}

async function fetchResumeTasks(): Promise<void> {
  resumeTasksLoading.value = true
  try {
    const response = await getTaskSummaryList()
    resumeTasks.value = response.items
  } catch {
    ElMessage.error('Failed to load task list for resume')
    resumeTasks.value = []
  } finally {
    resumeTasksLoading.value = false
  }
}

function handleModeChange(mode: string | number | boolean): void {
  if (mode === 'resume') {
    // Clear new-task state, load resume candidates
    formData.steps = []
    selectedResumeTaskId.value = null
    selectedResumeTask.value = null
    fetchResumeTasks()
  } else {
    // Clear resume state and stale POSCAR from previous session
    selectedResumeTaskId.value = null
    selectedResumeTask.value = null
    formData.steps = []
    poscarContent.value = ''
    poscarValidation.value = null
    poscarVersion.value++
  }
}

function handleResumeTaskSelected(task: TaskSummary | null): void {
  selectedResumeTask.value = task
  // Auto-initialize steps to resume_next_step when a task is selected
  if (task?.resume_next_step) {
    formData.steps = [task.resume_next_step]
  } else {
    formData.steps = []
  }
}

async function handleSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  const isResume = submitMode.value === 'resume'

  // Mode-specific validations
  if (isResume) {
    if (!selectedResumeTaskId.value || !selectedResumeTask.value) {
      ElMessage.error('Please select a task to resume from')
      return
    }
  } else {
    // Validate POSCAR uploaded
    if (!poscarContent.value) {
      ElMessage.error('Please upload a POSCAR file')
      return
    }
    // Validate POSCAR passed validation
    if (!poscarValidation.value?.valid) {
      ElMessage.error('Please fix POSCAR validation errors before submitting')
      return
    }
  }

  // Validate at least one step selected (redundant but explicit)
  if (formData.steps.length === 0) {
    ElMessage.error('At least one step must be selected')
    return
  }

  // Validate NAMD step requires inibands
  if (formData.steps.includes('namd')) {
    const namdInput = formData.namd_input as Record<string, unknown>
    const inibands = namdInput?.inibands
    if (!Array.isArray(inibands) || inibands.length === 0) {
      ElMessage.error('NAMD requires at least one initial band (inibands)')
      return
    }
  }

  // Build submit payload matching backend InputT exactly
  const payload = {
    basic_input: {
      software: formData.basic_input.software,
      plot: formData.basic_input.plot,
    },
    scheduler_config: {},
    steps: formData.steps,
    stru: isResume ? '' : poscarContent.value,
    stru_format: 'vasp',
    // Include inputs for selected steps
    ...(formData.steps.includes('nvt') && { nvt_input: formData.nvt_input }),
    ...(formData.steps.includes('nve') && { nve_input: formData.nve_input }),
    ...(formData.steps.includes('scf') && { scf_input: formData.scf_input }),
    ...(formData.steps.includes('pre_namd') && { prenamd_input: formData.prenamd_input }),
    ...(formData.steps.includes('namd') && { namd_input: formData.namd_input })
  }

  // Build URL with optional resume parameters
  let submitUrl = `/submit?method=${formData.method}`
  if (isResume) {
    submitUrl += `&resume=true&prev_task_id=${selectedResumeTaskId.value}`
  }

  submitting.value = true
  try {
    const response = await http.post<string>(submitUrl, payload)
    const taskId = response.data
    ElMessage.success(isResume ? `Task resumed: ${taskId}` : `Task submitted: ${taskId}`)
    router.push({ name: 'task-detail', params: { taskId } })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Submit failed'
    ElMessage.error(message)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.submit-task-page {
  padding: 24px;
  max-width: 900px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.page-title {
  margin: 0;
  font-size: 20px;
}

.submit-form {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.form-section {
  margin-bottom: 0;
}

.section-title {
  font-weight: 600;
  font-size: 16px;
}

.mode-section {
  margin-bottom: 0;
}

.mode-section :deep(.el-card__body) {
  display: flex;
  justify-content: center;
  padding: 16px;
}

.resume-info-alert {
  margin-bottom: 16px;
}

.validation-alert {
  margin-top: 16px;
}

.step-params {
  padding: 8px 0;
}

.step-params-title {
  margin: 0 0 16px 0;
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

.submit-section {
  display: flex;
  justify-content: center;
  padding: 24px 0;
}

.disabled-radio-wrapper {
  display: inline-block;
}

:deep(.param-help-icon) {
  font-size: 14px;
  color: var(--el-text-color-placeholder);
  cursor: help;
}
</style>
