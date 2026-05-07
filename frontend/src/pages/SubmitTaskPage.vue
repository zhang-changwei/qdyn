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

    <!-- Pool status display (pool-based mode) -->
    <el-card v-if="poolStatus" class="form-section pool-status-card">
      <template #header>
        <span class="section-title">Compute Pool</span>
      </template>
      <ul class="pool-description">
        <li>Each user can occupy up to <b>1</b> worker at a time.</li>
        <li>When the pool has free workers: your task goes to your active worker if you have one, or a free worker is assigned to you.</li>
        <li>When all workers are busy: your task enters a shared queue.
          When a worker frees up, users without a worker are served first;
          remaining queued tasks are then sent to their owners' active workers.</li>
      </ul>
      <div class="pool-status-info">
        <div class="pool-status-row">
          <span class="pool-label">Pool</span>
          <el-tag type="primary" size="small">{{ poolStatus.pool_name }}</el-tag>
        </div>
        <div class="pool-status-row">
          <span class="pool-label">Available Workers</span>
          <span class="pool-value">
            <span :class="{ 'pool-idle-zero': poolStatus.idle_workers === 0 }">
              {{ poolStatus.idle_workers }}
            </span>
            / {{ poolStatus.total_workers }}
          </span>
        </div>
        <div class="pool-status-row">
          <span class="pool-label">Your Workers</span>
          <el-tooltip
            :content="poolStatus.user_occupied_workers > 0
              ? (poolStatus.idle_workers > 0
                ? 'You have an active worker. New tasks will be submitted to it directly.'
                : 'You have an active worker, but all workers are busy. Your task will be queued and dispatched automatically.')
              : (poolStatus.idle_workers > 0
                ? 'No active worker. A free worker will be assigned when you submit.'
                : 'All workers are busy. Your task will be queued and dispatched automatically.')"
            placement="top"
          >
            <span class="pool-value pool-value-help">{{ poolStatus.user_occupied_workers }} / 1</span>
          </el-tooltip>
        </div>
        <el-alert
          v-if="poolStatus.idle_workers === 0"
          title="All workers are busy. Your task will be queued and dispatched automatically when a worker becomes available."
          type="info"
          :closable="false"
          show-icon
          class="pool-queue-hint"
        />
      </div>
    </el-card>

    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-position="top"
      class="submit-form"
      @submit.prevent
    >
      <!-- Task Name (always visible, all modes) -->
      <el-form-item label="Task Name" class="task-name-input">
        <el-input
          v-model="formData.taskName"
          placeholder="Custom task name (optional, defaults to formula)"
          :maxlength="50"
          show-word-limit
          clearable
        />
      </el-form-item>

      <!-- Resume task selector (resume mode only) -->
      <el-card v-if="submitMode === 'resume'" class="form-section">
        <template #header>
          <span class="section-title">1. Select Previous Task</span>
        </template>
        <el-alert
          title="Structure will be inherited from the selected task. Only tasks from the same compute pool are shown — cross-pool resume is not supported as run directory paths differ between pools."
          type="info"
          show-icon
          :closable="false"
          class="resume-info-alert"
        />
        <ResumeTaskSelector
          v-model="selectedResumeTaskId"
          :tasks="resumeTasks"
          :loading="resumeTasksLoading"
          :selected-pool="selectedPool"
          @task-selected="handleResumeTaskSelected"
        />
        <StructureViewer v-if="structurePreview" :preview="structurePreview" class="structure-preview" />
        <el-alert
          v-if="fileHasConstraints"
          type="info"
          :closable="false"
          show-icon
          class="constraint-file-hint"
        >
          Structure file already contains fixed atoms (selective dynamics). Constraint Layers will be ignored.
        </el-alert>
      </el-card>

      <!-- Step selection section — shown first so user picks steps before uploading -->
      <el-card class="form-section">
        <template #header>
          <span class="section-title">{{ submitMode === 'resume' ? '2' : '1' }}. Workflow Steps</span>
        </template>
        <el-form-item prop="steps">
          <StepSelector
            v-model="formData.steps"
            :resume="submitMode === 'resume'"
            :completed-steps="selectedResumeTask?.completed_steps"
          />
        </el-form-item>
      </el-card>

      <!-- Structure upload — only for new tasks, after steps are chosen -->
      <!-- POSCAR upload (NVT/NVE first step) -->
      <el-card v-if="submitMode === 'new' && formData.steps.length > 0 && !isSCFFirstStep" class="form-section">
        <template #header>
          <span class="section-title">2. Structure (POSCAR)</span>
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
        <StructureViewer v-if="structurePreview" :preview="structurePreview" class="structure-preview" />
        <el-alert
          v-if="fileHasConstraints"
          type="info"
          :closable="false"
          show-icon
          class="constraint-file-hint"
        >
          Structure file already contains fixed atoms (selective dynamics). Constraint Layers will be ignored.
        </el-alert>
      </el-card>

      <!-- Trajectory upload (SCF first step) -->
      <el-card v-if="submitMode === 'new' && isSCFFirstStep" class="form-section">
        <template #header>
          <span class="section-title">2. Trajectory File</span>
        </template>
        <div
          class="traj-uploader"
          :class="{ 'is-dragover': trajDragover }"
          @dragenter.prevent="trajDragover = true"
          @dragover.prevent="trajDragover = true"
          @dragleave.prevent="trajDragover = false"
          @drop.prevent="handleTrajDrop"
          @click="triggerTrajInput"
        >
          <input
            ref="trajInputRef"
            type="file"
            hidden
            @change="handleTrajFileChange"
          />

          <!-- idle state -->
          <div v-if="trajStatus === 'idle'" class="upload-prompt">
            <el-icon class="upload-icon" :size="40"><Upload /></el-icon>
            <div class="upload-text">
              <span>Drag trajectory file here or </span>
              <el-button type="primary" link>click to upload</el-button>
            </div>
            <div class="upload-hint">
              Supports XDATCAR or other trajectory formats
            </div>
          </div>

          <!-- hashing / checking / uploading / done / error -->
          <div v-else class="traj-status-area" @click.stop>
            <div class="traj-file-info">
              <el-icon><Document /></el-icon>
              <span class="traj-file-name">{{ trajFileName }}</span>
              <span class="traj-file-size">({{ formatFileSize(trajFileSize) }})</span>
              <el-button
                v-if="trajStatus !== 'uploading'"
                type="danger"
                link
                @click.stop="clearTrajFile"
              >
                Remove
              </el-button>
            </div>

            <!-- hashing progress -->
            <div v-if="trajStatus === 'hashing'" class="traj-progress-row">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>Calculating file hash...</span>
              <el-progress
                :percentage="trajHashProgress"
                :show-text="true"
                :stroke-width="8"
                style="flex: 1; margin-left: 8px;"
              />
            </div>

            <!-- checking server -->
            <div v-if="trajStatus === 'checking'" class="traj-progress-row">
              <el-icon class="is-loading"><Loading /></el-icon>
              <span>Checking server...</span>
            </div>

            <!-- uploading progress -->
            <div v-if="trajStatus === 'uploading'" class="traj-progress-row">
              <span>Uploading...</span>
              <el-progress
                :percentage="trajUploadProgress"
                :show-text="true"
                :stroke-width="8"
                status="warning"
                style="flex: 1; margin-left: 8px;"
              />
            </div>

            <!-- done -->
            <div v-if="trajStatus === 'done'" class="traj-done-area">
              <div class="traj-progress-row traj-done">
                <el-icon color="var(--el-color-success)"><SuccessFilled /></el-icon>
                <span>{{ trajSkippedUpload ? 'File already on server' : 'Upload complete' }}</span>
              </div>
              <div v-if="trajSummary" class="traj-summary">
                {{ trajSummary.formula }} · {{ trajSummary.num_atoms }} atoms{{ trajSummary.num_frames ? ` · ${trajSummary.num_frames} frames` : '' }}
              </div>
              <div class="traj-hash-display">
                MD5: <code>{{ trajHash }}</code>
              </div>
            </div>

            <!-- error -->
            <div v-if="trajStatus === 'error'" class="traj-progress-row traj-error">
              <el-icon color="var(--el-color-danger)"><CircleClose /></el-icon>
              <span>{{ trajErrorMsg }}</span>
              <el-button type="primary" link @click.stop="retryTrajUpload">Retry</el-button>
            </div>
          </div>
        </div>
      </el-card>

      <!-- Method & Basic Settings section -->
      <el-card class="form-section">
        <template #header>
          <span class="section-title">{{ submitMode === 'resume' ? '3' : '3' }}. Method & Settings</span>
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
          <template v-for="(step, stepIdx) in formData.steps" :key="step">
            <!-- Fused mode info alert -->
            <el-alert
              v-if="step === 'fused_scf_prenamd'"
              title="Fused mode forces single-node execution for SCF"
              type="info"
              :closable="false"
              show-icon
              style="margin-bottom: 12px;"
            />
            <template v-for="(entry, entryIdx) in getStepInputEntries(step)" :key="entry.inputKey">
              <el-divider v-if="stepIdx > 0 || entryIdx > 0" />
              <div class="step-params">
                <h4 class="step-params-title">{{ entry.label }}</h4>
                <DynamicStepForm
                  :schema="schemas[entry.schemaKey]"
                  :model-value="formData[entry.inputKey] as Record<string, unknown>"
                  @update:model-value="formData[entry.inputKey] = $event as any"
                />
              </div>
            </template>
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
          :disabled="isSubmitDisabled"
          @click="handleSubmit"
        >
          {{ submitMode === 'resume' ? 'Resume Task' : 'Submit Task' }}
        </el-button>
      </div>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, QuestionFilled, Upload, Document, Loading, SuccessFilled, CircleClose } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import SparkMD5 from 'spark-md5'
import PoscarUploader from '@/components/PoscarUploader.vue'
import StepSelector from '@/components/StepSelector.vue'
import ResumeTaskSelector from '@/components/ResumeTaskSelector.vue'
import DynamicStepForm from '@/components/DynamicStepForm.vue'
import StructureViewer from '@/components/StructureViewer.vue'
import { validatePoscar, computeConstraintMask, getTaskStructurePreview } from '@/api/structures'
import { getStepInputSchemas, type StepInputSchemas } from '@/api/schema'
import { getTaskSummaryList, uploadTrajectory, checkTrajectoryHash, getPoolStatus } from '@/api/tasks'
import { buildDefaultsFromSchema } from '@/utils/schema-form'
import http from '@/api/http'
import type { ValidatePoscarResponse, TaskSummary, SubmitResponse, PoolStatusResponse, StructurePreviewPayload, ComputeConstraintMaskRequest, NVTInput, NVEInput, SCFInput, PreNAMDInput, NAMDInput } from '@/api/types'

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

interface StepInputEntry {
  inputKey: keyof typeof formData
  schemaKey: keyof StepInputSchemas
  label: string
}

function getStepInputEntries(step: string): StepInputEntry[] {
  if (step === 'fused_scf_prenamd') {
    return [
      { inputKey: 'scf_input', schemaKey: 'scf', label: 'SCF Parameters' },
      { inputKey: 'prenamd_input', schemaKey: 'pre_namd', label: 'Pre-NAMD Parameters' },
    ]
  }
  const config = STEP_CONFIG[step]
  return config ? [{ inputKey: config.inputKey, schemaKey: config.schemaKey, label: config.label }] : []
}

const router = useRouter()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const poscarContent = ref('')
const poscarValidation = ref<ValidatePoscarResponse | null>(null)
const poscarVersion = ref(0) // Used to prevent race condition in validation
const structurePreview = ref<StructurePreviewPayload | null>(null)
const basePreview = ref<StructurePreviewPayload | null>(null)
const schemas = ref<StepInputSchemas | null>(null)

// Constraint mask debounce state
let constraintDebounceTimer: ReturnType<typeof setTimeout> | null = null
let constraintRequestId = 0 // monotonic counter to discard stale responses
/** Whether the uploaded structure file has built-in constraints (selective dynamics). */
const fileHasConstraints = computed(() => {
  const mask = basePreview.value?.constraint_mask
  return Array.isArray(mask) && mask.some(Boolean)
})
const CONSTRAINT_DEBOUNCE_MS = 400

// Pool status
const poolStatus = ref<PoolStatusResponse | null>(null)
const selectedPool = ref<string>('')

// Resume mode state
const submitMode = ref<'new' | 'resume'>('new')
const resumeTasks = ref<TaskSummary[]>([])
const resumeTasksLoading = ref(false)
const selectedResumeTaskId = ref<string | null>(null)
const selectedResumeTask = ref<TaskSummary | null>(null)

// Trajectory upload state
type TrajStatus = 'idle' | 'hashing' | 'checking' | 'uploading' | 'done' | 'error'
const trajInputRef = ref<HTMLInputElement>()
const trajDragover = ref(false)
const trajStatus = ref<TrajStatus>('idle')
const trajFile = ref<File | null>(null)
const trajFileName = ref('')
const trajFileSize = ref(0)
const trajHash = ref('')
const trajHashProgress = ref(0)
const trajUploadProgress = ref(0)
const trajSkippedUpload = ref(false)
const trajSummary = ref<{ formula: string; num_atoms: number; num_frames?: number } | null>(null)
const trajErrorMsg = ref('')
const trajVersion = ref(0) // Concurrency guard: prevents stale async flows from overwriting state

/**
 * Whether the first selected step is SCF (and not resume mode).
 * Determines if trajectory upload should be shown instead of POSCAR.
 */
const isSCFFirstStep = computed(() => {
  if (submitMode.value !== 'new') return false
  if (formData.steps.length === 0) return false
  return formData.steps[0] === 'scf' || formData.steps[0] === 'fused_scf_prenamd'
})

/**
 * Whether the submit button should be disabled due to ongoing upload operations.
 */
const isSubmitDisabled = computed(() => {
  if (isSCFFirstStep.value) {
    return ['hashing', 'checking', 'uploading'].includes(trajStatus.value)
  }
  return false
})

/**
 * Extract constraint parameters from the currently active step (NVT or NVE).
 * Returns null if no relevant step is selected.
 */
const activeConstraintParams = computed(() => {
  const steps = formData.steps
  // Only NVT and NVE have constraint parameters (nested under sel)
  for (const step of steps) {
    if (step === 'nvt') {
      const input = formData.nvt_input as Record<string, unknown>
      const sel = (input?.sel as Record<string, unknown>) ?? {}
      return {
        constraint_layers: (sel?.constraint_layers as string) ?? '',
        layer_direction: (sel?.layer_direction as string) ?? '',
        total_layers: sel?.total_layers as number | null | undefined,
      }
    }
    if (step === 'nve') {
      const input = formData.nve_input as Record<string, unknown>
      const sel = (input?.sel as Record<string, unknown>) ?? {}
      return {
        constraint_layers: (sel?.constraint_layers as string) ?? '',
        layer_direction: (sel?.layer_direction as string) ?? '',
        total_layers: sel?.total_layers as number | null | undefined,
      }
    }
  }
  return null
})

/**
 * Local gate: check if constraint parameters are complete and syntactically
 * plausible before sending a request to the backend.
 * Avoids spamming the API with half-typed inputs.
 */
function isConstraintParamsReady(params: {
  constraint_layers: string
  layer_direction: string
  total_layers: number | null | undefined
}): boolean {
  // All three parameters must be present
  if (!params.constraint_layers || !params.layer_direction) return false
  if (params.total_layers == null || params.total_layers < 1) return false
  // total_layers must be a positive integer
  if (!Number.isInteger(params.total_layers)) return false
  // constraint_layers must match backend parse_constraint_layers_spec() syntax:
  // space-separated tokens, each a number or tight dash range (no spaces around dash)
  // Valid: "1-3 5", "1 2 3"  Invalid: "1 - 3", "1-", "-3"
  if (!/^\d+(?:-\d+)?(?:\s+\d+(?:-\d+)?)*$/.test(params.constraint_layers.trim())) return false
  return true
}

onMounted(async () => {
  // Fetch pool info
  try {
    const resp = await http.get<{ workers: string[]; default: string }>('/workers')
    selectedPool.value = resp.data.default
  } catch {
    // Fallback: selector stays hidden
  }

  // Fetch pool status
  try {
    poolStatus.value = await getPoolStatus()
    if (poolStatus.value) {
      selectedPool.value = poolStatus.value.pool_name
    }
  } catch {
    poolStatus.value = null
  }

  try {
    schemas.value = await getStepInputSchemas()
    // Backfill defaults for any steps already selected before schema loaded
    for (const step of formData.steps) {
      for (const entry of getStepInputEntries(step)) {
        const current = formData[entry.inputKey]
        if (!current || Object.keys(current as object).length === 0) {
          ;(formData as Record<string, unknown>)[entry.inputKey] = buildStepDefaults(entry.schemaKey)
        }
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
  taskName: string
  basic_input: { software: string; plot: boolean }
  nvt_input: NVTInput | Record<string, unknown>
  nve_input: NVEInput | Record<string, unknown>
  scf_input: SCFInput | Record<string, unknown>
  prenamd_input: PreNAMDInput | Record<string, unknown>
  namd_input: NAMDInput | Record<string, unknown>
}>({
  steps: [],
  method: 'namd',
  taskName: '',
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

// Watch steps changes to init/reset input objects from schema defaults.
// Uses inputKey active sets so scf↔fused toggle does not reset shared inputs.
watch(
  () => formData.steps,
  (newSteps, oldSteps) => {
    const newInputKeys = new Set(
      newSteps.flatMap(s => getStepInputEntries(s).map(e => e.inputKey))
    )
    const oldInputKeys = new Set(
      (oldSteps ?? []).flatMap(s => getStepInputEntries(s).map(e => e.inputKey))
    )

    // Initialize: fill any input that is needed but empty
    for (const key of newInputKeys) {
      const current = formData[key]
      if (!current || Object.keys(current as object).length === 0) {
        const entry = newSteps
          .flatMap(s => getStepInputEntries(s))
          .find(e => e.inputKey === key)
        if (entry) {
          ;(formData as Record<string, unknown>)[key] = buildStepDefaults(entry.schemaKey)
        }
      }
    }

    // Reset: only clear inputs that old steps used but new steps no longer need
    for (const key of oldInputKeys) {
      if (!newInputKeys.has(key)) {
        const entry = (oldSteps ?? [])
          .flatMap(s => getStepInputEntries(s))
          .find(e => e.inputKey === key)
        if (entry) {
          ;(formData as Record<string, unknown>)[key] = buildStepDefaults(entry.schemaKey)
        }
      }
    }
  },
  { deep: true }
)

watch(selectedPool, (newPool, oldPool) => {
  if (!oldPool || newPool === oldPool) {
    return
  }
  selectedResumeTaskId.value = null
  selectedResumeTask.value = null
  formData.steps = []
})

// ---------------------------------------------------------------------------
// Constraint mask real-time computation
// ---------------------------------------------------------------------------

/**
 * Watch constraint parameters AND basePreview, debounce API calls to compute
 * the constraint mask for the 3D preview.
 *
 * Triggers when:
 * - User changes constraint_layers / layer_direction / total_layers in form
 * - A new structure is uploaded (basePreview changes)
 *
 * Uses constraintRequestId to discard stale responses after rapid changes.
 */
watch(
  [activeConstraintParams, basePreview] as const,
  ([params, base]) => {
    // Clear any pending debounce timer
    if (constraintDebounceTimer !== null) {
      clearTimeout(constraintDebounceTimer)
      constraintDebounceTimer = null
    }

    // If no constraint params or params incomplete, revert to basePreview
    if (!params || !isConstraintParamsReady(params)) {
      if (base) {
        structurePreview.value = { ...base }
      }
      return
    }

    // Need either uploaded content or a resume task to compute against
    if (!poscarContent.value && !selectedResumeTask.value) return
    if (!base) return

    // Bump request ID and capture it for staleness check
    const myRequestId = ++constraintRequestId

    // Debounce the API call
    constraintDebounceTimer = setTimeout(async () => {
      constraintDebounceTimer = null
      try {
        // Build request: use stru_content if available, otherwise task_id
        const requestPayload: ComputeConstraintMaskRequest = poscarContent.value
          ? {
              stru_content: poscarContent.value,
              stru_format: 'vasp',
              constraint_layers: params.constraint_layers,
              layer_direction: params.layer_direction,
              total_layers: params.total_layers!,
            }
          : {
              task_id: selectedResumeTask.value!.task_id,
              constraint_layers: params.constraint_layers,
              layer_direction: params.layer_direction,
              total_layers: params.total_layers!,
            }
        const result = await computeConstraintMask(requestPayload)
        // Only apply if this is still the latest request
        if (constraintRequestId !== myRequestId) return
        if (basePreview.value) {
          structurePreview.value = {
            ...basePreview.value,
            constraint_mask: result.constraint_mask,
          }
        }
      } catch {
        // Silently degrade — do not toast or disrupt user input flow.
        if (constraintRequestId !== myRequestId) return
        if (basePreview.value) {
          structurePreview.value = { ...basePreview.value }
        }
      }
    }, CONSTRAINT_DEBOUNCE_MS)
  },
  { deep: true }
)

// ---------------------------------------------------------------------------
// POSCAR upload handlers (existing)
// ---------------------------------------------------------------------------

async function handlePoscarLoaded(content: string): Promise<void> {
  poscarContent.value = content
  poscarVersion.value++ // Increment version to track this request
  constraintRequestId++ // Invalidate any in-flight constraint requests
  const currentVersion = poscarVersion.value
  poscarValidation.value = null
  structurePreview.value = null
  basePreview.value = null

  try {
    const result = await validatePoscar(content)
    // Only update validation if this is the latest request
    if (poscarVersion.value === currentVersion) {
      poscarValidation.value = result
      const preview = result.preview ?? null
      basePreview.value = preview
      structurePreview.value = preview
    }
  } catch (error) {
    // Only update error if this is the latest request
    if (poscarVersion.value === currentVersion) {
      poscarValidation.value = {
        valid: false,
        error: error instanceof Error ? error.message : 'Validation failed'
      }
      basePreview.value = null
      structurePreview.value = null
    }
  }
}

function handlePoscarCleared(): void {
  poscarContent.value = ''
  poscarValidation.value = null
  basePreview.value = null
  structurePreview.value = null
  poscarVersion.value++
  constraintRequestId++ // Invalidate any in-flight constraint requests
}

// ---------------------------------------------------------------------------
// Trajectory upload handlers
// ---------------------------------------------------------------------------

/**
 * Compute MD5 hash of a file using spark-md5 with streaming chunks.
 * Yields progress callbacks to avoid blocking the UI.
 */
async function computeFileMD5(file: File, onProgress?: (percent: number) => void): Promise<string> {
  const chunkSize = 4 * 1024 * 1024 // 4 MiB
  const spark = new SparkMD5.ArrayBuffer()
  let offset = 0
  while (offset < file.size) {
    const end = Math.min(offset + chunkSize, file.size)
    const chunk = await file.slice(offset, end).arrayBuffer()
    spark.append(chunk)
    offset = end
    if (onProgress) onProgress(Math.round((offset / file.size) * 100))
  }
  return spark.end()
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function triggerTrajInput(): void {
  if (trajStatus.value === 'idle') {
    trajInputRef.value?.click()
  }
}

function handleTrajDrop(e: DragEvent): void {
  trajDragover.value = false
  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    processTrajFile(files[0])
  }
}

function handleTrajFileChange(e: Event): void {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    processTrajFile(input.files[0])
  }
  // Reset input value so selecting the same file again triggers change
  input.value = ''
}

function clearTrajFile(): void {
  trajVersion.value++ // Invalidate any in-flight async operations
  trajFile.value = null
  trajFileName.value = ''
  trajFileSize.value = 0
  trajHash.value = ''
  trajHashProgress.value = 0
  trajUploadProgress.value = 0
  trajSkippedUpload.value = false
  trajSummary.value = null
  trajErrorMsg.value = ''
  trajStatus.value = 'idle'
}

async function processTrajFile(file: File): Promise<void> {
  // Capture a version token; if it changes during async work, bail out
  const myVersion = ++trajVersion.value

  // Reset state
  trajFile.value = file
  trajFileName.value = file.name
  trajFileSize.value = file.size
  trajHash.value = ''
  trajHashProgress.value = 0
  trajUploadProgress.value = 0
  trajSkippedUpload.value = false
  trajSummary.value = null
  trajErrorMsg.value = ''

  try {
    // Step 1: Compute hash
    trajStatus.value = 'hashing'
    const hash = await computeFileMD5(file, (p) => {
      if (trajVersion.value === myVersion) trajHashProgress.value = p
    })
    if (trajVersion.value !== myVersion) return // Superseded by newer operation
    trajHash.value = hash

    // Step 2: Check server
    trajStatus.value = 'checking'
    const checkResult = await checkTrajectoryHash(hash)
    if (trajVersion.value !== myVersion) return // Superseded

    if (checkResult.exists) {
      // File already on server, skip upload
      trajSkippedUpload.value = true
      if (checkResult.formula) {
        trajSummary.value = {
          formula: checkResult.formula,
          num_atoms: checkResult.num_atoms ?? 0,
          num_frames: checkResult.num_frames,
        }
      }
      trajStatus.value = 'done'
      return
    }

    // Step 3: Upload
    trajStatus.value = 'uploading'
    const uploadResult = await uploadTrajectory(file, (p) => {
      if (trajVersion.value === myVersion) trajUploadProgress.value = p
    })
    if (trajVersion.value !== myVersion) return // Superseded
    if (uploadResult.formula) {
      trajSummary.value = {
        formula: uploadResult.formula,
        num_atoms: uploadResult.num_atoms ?? 0,
        num_frames: uploadResult.num_frames,
      }
    }
    trajStatus.value = 'done'
  } catch (err) {
    if (trajVersion.value !== myVersion) return // Superseded; discard stale error
    // Extract detail from axios error response, fall back to generic message
    const axiosErr = err as any
    trajErrorMsg.value = axiosErr?.response?.data?.detail
      || (err instanceof Error ? err.message : 'Upload failed')
    trajStatus.value = 'error'
  }
}

function retryTrajUpload(): void {
  if (trajFile.value) {
    processTrajFile(trajFile.value)
  }
}

// ---------------------------------------------------------------------------
// Navigation and mode handling
// ---------------------------------------------------------------------------

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
  formData.taskName = ''
  constraintRequestId++ // Invalidate any in-flight constraint requests
  if (mode === 'resume') {
    // Clear new-task state, load resume candidates
    formData.steps = []
    selectedResumeTaskId.value = null
    selectedResumeTask.value = null
    basePreview.value = null
    structurePreview.value = null
    clearTrajFile()
    fetchResumeTasks()
  } else {
    // Clear resume state and stale POSCAR from previous session
    selectedResumeTaskId.value = null
    selectedResumeTask.value = null
    formData.steps = []
    poscarContent.value = ''
    poscarValidation.value = null
    basePreview.value = null
    structurePreview.value = null
    poscarVersion.value++
    clearTrajFile()
  }
}

async function handleResumeTaskSelected(task: TaskSummary | null): Promise<void> {
  selectedResumeTask.value = task
  constraintRequestId++ // Invalidate in-flight constraint requests
  poscarVersion.value++ // Use as stale guard for resume preview requests
  const currentVersion = poscarVersion.value
  // Auto-initialize steps to resume_next_step when a task is selected
  if (task?.resume_next_step) {
    formData.steps = [task.resume_next_step]
  } else {
    formData.steps = []
  }
  // Inherit task_name from the previous task only if user hasn't typed one
  if (!formData.taskName.trim()) {
    formData.taskName = task?.task_name || task?.formula || ''
  }
  // Fetch structure preview from the parent task
  if (task) {
    try {
      const preview = await getTaskStructurePreview(task.task_id, { raw: true })
      if (poscarVersion.value !== currentVersion) return // stale
      basePreview.value = preview
      structurePreview.value = preview
    } catch {
      if (poscarVersion.value !== currentVersion) return
      basePreview.value = null
      structurePreview.value = null
    }
  } else {
    basePreview.value = null
    structurePreview.value = null
  }
}

// ---------------------------------------------------------------------------
// Submit
// ---------------------------------------------------------------------------

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
  } else if (isSCFFirstStep.value) {
    // SCF first step: require trajectory hash
    if (trajStatus.value !== 'done' || !trajHash.value) {
      ElMessage.error('Please upload a trajectory file first')
      return
    }
  } else {
    // NVT/NVE first step: require POSCAR
    if (!poscarContent.value) {
      ElMessage.error('Please upload a POSCAR file')
      return
    }
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

  // Fused mode: force scf_input.nodes = 1 before payload construction
  if (formData.steps.includes('fused_scf_prenamd')) {
    const scfInput = formData.scf_input as Record<string, unknown>
    if (scfInput) {
      scfInput.nodes = 1
    }
  }

  // Build submit payload matching backend InputT exactly
  const useTrajHash = !isResume && isSCFFirstStep.value && !!trajHash.value

  // Collect active input keys via getStepInputEntries
  const activeInputKeys = new Set(
    formData.steps.flatMap(s => getStepInputEntries(s).map(e => e.inputKey))
  )

  const payload: Record<string, unknown> = {
    basic_input: {
      software: formData.basic_input.software,
      plot: formData.basic_input.plot,
    },
    scheduler_config: {},
    steps: formData.steps,
    stru: useTrajHash ? '' : (isResume ? '' : poscarContent.value),
    stru_format: 'vasp',
    ...(useTrajHash ? { stru_hash: trajHash.value } : {}),
    task_name: formData.taskName.trim() || null,
  }

  // Include inputs for all active steps (covers fused → scf_input + prenamd_input)
  if (activeInputKeys.has('nvt_input')) payload.nvt_input = formData.nvt_input
  if (activeInputKeys.has('nve_input')) payload.nve_input = formData.nve_input
  if (activeInputKeys.has('scf_input')) payload.scf_input = formData.scf_input
  if (activeInputKeys.has('prenamd_input')) payload.prenamd_input = formData.prenamd_input
  if (activeInputKeys.has('namd_input')) payload.namd_input = formData.namd_input

  // Build URL with optional resume parameters
  let submitUrl = `/submit?method=${formData.method}`
  if (isResume) {
    submitUrl += `&resume=true&prev_task_id=${selectedResumeTaskId.value}`
  }

  submitting.value = true
  try {
    const response = await http.post<SubmitResponse>(submitUrl, payload)
    const result = response.data

    if (result.status === 'QUEUED') {
      const posMsg = result.queue_position ? ` (position #${result.queue_position})` : ''
      ElMessage.info(`Task queued${posMsg}. It will be dispatched when a worker becomes available.`)
      router.push({ name: 'task-list' })
    } else {
      const label = isResume ? 'Task resumed' : 'Task submitted'
      ElMessage.success(`${label}: ${result.task_id}`)
      router.push({ name: 'task-detail', params: { taskId: result.task_id } })
    }
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
  display: inline-flex;
  vertical-align: middle;
}

:deep(.param-help-icon) {
  font-size: 14px;
  color: var(--el-text-color-placeholder);
  cursor: help;
}

/* Trajectory uploader styles */
/* Trajectory uploader — visually matched to PoscarUploader */
.traj-uploader {
  border: 2px dashed var(--el-border-color);
  border-radius: 8px;
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color 0.2s, background-color 0.2s;
  background-color: var(--el-fill-color-blank);
}

.traj-uploader:hover {
  border-color: var(--el-color-primary);
  background-color: var(--el-fill-color-light);
}

.traj-uploader.is-dragover {
  border-color: var(--el-color-primary);
  background-color: var(--el-color-primary-light-9);
}

.upload-prompt {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.upload-icon {
  font-size: 48px;
  color: var(--el-text-color-placeholder);
}

.upload-text {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--el-text-color-secondary);
}

.upload-hint {
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}

.traj-status-area {
  cursor: default;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.traj-file-info {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.traj-file-name {
  font-weight: 500;
}

.traj-file-size {
  color: var(--el-text-color-secondary);
}

.traj-progress-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.traj-done {
  color: var(--el-color-success);
}

.traj-error {
  color: var(--el-color-danger);
}

.traj-done-area {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.traj-summary {
  font-size: 14px;
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.traj-hash-display {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.traj-hash-display code {
  font-family: monospace;
  background: var(--el-fill-color-light);
  padding: 1px 4px;
  border-radius: 3px;
}

/* Pool status card */
.pool-description {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
  margin: 0 0 12px 0;
  padding-left: 20px;
}
.pool-description li {
  margin-bottom: 2px;
}

.pool-value-help {
  cursor: help;
  border-bottom: 1px dashed var(--el-text-color-secondary);
}

.pool-status-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.pool-status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 0;
}

.pool-label {
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

.pool-value {
  font-size: 14px;
  font-weight: 500;
}

.pool-idle-zero {
  color: var(--el-color-warning);
  font-weight: 600;
}

.pool-queue-hint {
  margin-top: 8px;
}

.task-name-input {
  margin-top: 16px;
  margin-bottom: 0;
}

.structure-preview {
  margin-top: 16px;
}

.constraint-file-hint {
  margin-top: 8px;
}
</style>
