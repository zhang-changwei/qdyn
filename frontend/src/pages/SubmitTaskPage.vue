<template>
  <div class="submit-task-page">
    <!-- Header -->
    <div class="page-header">
      <el-button @click="goBack">
        <el-icon><ArrowLeft /></el-icon>
        Back
      </el-button>
      <h2 class="page-title">Submit New Task</h2>
    </div>

    <el-form
      ref="formRef"
      :model="formData"
      :rules="formRules"
      label-position="top"
      class="submit-form"
    >
      <!-- POSCAR upload section -->
      <el-card class="form-section">
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

      <!-- Step selection section -->
      <el-card class="form-section">
        <template #header>
          <span class="section-title">2. Workflow Steps</span>
        </template>
        <el-form-item prop="steps">
          <StepSelector v-model="formData.steps" :resume="false" />
        </el-form-item>
      </el-card>

      <!-- Method selection section -->
      <el-card class="form-section">
        <template #header>
          <span class="section-title">3. Method</span>
        </template>
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
      </el-card>

      <!-- Parameter configuration section -->
      <el-card v-if="formData.steps.length > 0" class="form-section">
        <template #header>
          <span class="section-title">4. Step Parameters</span>
        </template>

        <!-- NVT parameters -->
        <div v-if="formData.steps.includes('nvt')" class="step-params">
          <h4 class="step-params-title">NVT Parameters</h4>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>Initial Temperature (K) <el-tooltip content="Initial temperature in K" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.nvt_input.temp_begin"
                  :min="1"
                  :max="10000"
                  :step="50"
                  :precision="1"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>Final Temperature (K) <el-tooltip content="Final temperature in K" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.nvt_input.temp_end"
                  :min="1"
                  :max="10000"
                  :step="50"
                  :precision="1"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>MD Time Step (fs) <el-tooltip content="MD time step in fs" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.nvt_input.md_dt"
                  :min="0.1"
                  :max="10"
                  :step="0.5"
                  :precision="1"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>Number of MD Steps <el-tooltip content="Number of MD steps" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.nvt_input.md_step"
                  :min="100"
                  :max="100000"
                  :step="500"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>K-point Spacing (1/Å) <el-tooltip content="K-point spacing in 2π × 1/Å" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.nvt_input.kspacing"
                  :min="0.01"
                  :max="1"
                  :precision="3"
                  :step="0.01"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>Thermostat <el-tooltip content="MD thermostat method" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-select v-model="formData.nvt_input.md_thermostat">
                  <el-option label="Rescale V" value="rescale_v" />
                  <el-option label="NHC" value="nhc" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>SCF Threshold <el-tooltip content="Electronic convergence criterion (eV)" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-select v-model="formData.nvt_input.scf_thr">
                  <el-option v-for="v in scfThrOptions" :key="v" :label="v.toExponential()" :value="v" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- NVE parameters -->
        <el-divider v-if="formData.steps.includes('nvt') && formData.steps.includes('nve')" />
        <div v-if="formData.steps.includes('nve')" class="step-params">
          <h4 class="step-params-title">NVE Parameters</h4>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>MD Time Step (fs) <el-tooltip content="MD time step in fs" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.nve_input.md_dt"
                  :min="0.1"
                  :max="10"
                  :step="0.5"
                  :precision="1"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>Number of MD Steps <el-tooltip content="Number of MD steps" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.nve_input.md_step"
                  :min="100"
                  :max="100000"
                  :step="500"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>K-point Spacing (1/Å) <el-tooltip content="K-point spacing in 2π × 1/Å" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.nve_input.kspacing"
                  :min="0.01"
                  :max="1"
                  :precision="3"
                  :step="0.01"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>SCF Threshold <el-tooltip content="Electronic convergence criterion (eV)" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-select v-model="formData.nve_input.scf_thr">
                  <el-option v-for="v in scfThrOptions" :key="v" :label="v.toExponential()" :value="v" />
                </el-select>
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- SCF parameters -->
        <el-divider v-if="formData.steps.includes('nve') && formData.steps.includes('scf')" />
        <div v-if="formData.steps.includes('scf')" class="step-params">
          <h4 class="step-params-title">SCF Parameters</h4>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>Number of SCF Frames <el-tooltip content="Number of SCF frames to calculate" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.scf_input.scf_step"
                  :min="1"
                  :max="10000"
                  :step="100"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>Batch Size <el-tooltip content="Number of frames per batch task. Smaller batches mean more parallel tasks." placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.scf_input.batch_size"
                  :min="1"
                  :max="500"
                  :step="10"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>K-point Spacing (1/Å) <el-tooltip content="K-point spacing in 2π × 1/Å" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input-number
                  v-model="formData.scf_input.kspacing"
                  :min="0.01"
                  :max="1"
                  :precision="3"
                  :step="0.01"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>SCF Threshold <el-tooltip content="Electronic convergence criterion (eV)" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-select v-model="formData.scf_input.scf_thr">
                  <el-option v-for="v in scfThrOptions" :key="v" :label="v.toExponential()" :value="v" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>All-electron VASP <el-tooltip content="Whether to use all-electron vasp" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-switch v-model="formData.scf_input.is_alle" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- Pre-NAMD parameters -->
        <el-divider v-if="formData.steps.includes('scf') && formData.steps.includes('pre_namd')" />
        <div v-if="formData.steps.includes('pre_namd')" class="step-params">
          <h4 class="step-params-title">Pre-NAMD Parameters</h4>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>Band Min <el-tooltip content="Lower band index. Use VBM, VBM-2, VBM+1, or integer" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input
                  v-model="formData.prenamd_input.bmin"
                  placeholder="e.g. VBM, VBM-2, 10"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item>
                <template #label>
                  <span>Band Max <el-tooltip content="Upper band index. Use CBM, CBM+4, VBM+10, or integer" placement="top" :show-after="300"><el-icon class="param-help-icon"><QuestionFilled /></el-icon></el-tooltip></span>
                </template>
                <el-input
                  v-model="formData.prenamd_input.bmax"
                  placeholder="e.g. CBM, CBM+4, 20"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="MD Time Step (fs)">
                <el-input-number
                  v-model="formData.prenamd_input.md_dt"
                  :min="0.1"
                  :max="10"
                  :precision="2"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Surface Hopping Method">
                <el-select v-model="formData.prenamd_input.surface_hopping">
                  <el-option label="DISH" value="DISH" />
                  <el-option label="FSSH" value="FSSH" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Adiabatic Representation">
                <el-switch v-model="formData.prenamd_input.adiabatic_rep" />
              </el-form-item>
            </el-col>
          </el-row>
        </div>

        <!-- NAMD parameters -->
        <el-divider v-if="formData.steps.includes('pre_namd') && formData.steps.includes('namd')" />
        <div v-if="formData.steps.includes('namd')" class="step-params">
          <h4 class="step-params-title">NAMD Parameters</h4>
          <el-row :gutter="16">
            <el-col :span="8">
              <el-form-item label="MD Time Step (fs)">
                <el-input-number
                  v-model="formData.namd_input.md_dt"
                  :min="0.1"
                  :max="10"
                  :precision="2"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Temperature (K)">
                <el-input-number
                  v-model="formData.namd_input.temperature"
                  :min="1"
                  :max="10000"
                  :precision="1"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Surface Hopping Method">
                <el-select v-model="formData.namd_input.surface_hopping">
                  <el-option label="DISH" value="DISH" />
                  <el-option label="FSSH" value="FSSH" />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Adiabatic Representation">
                <el-switch v-model="formData.namd_input.adiabatic_rep" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Number of Samples">
                <el-input-number
                  v-model="formData.namd_input.nsample"
                  :min="1"
                  :max="10000"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Number of Trajectories">
                <el-input-number
                  v-model="formData.namd_input.ntraj"
                  :min="1"
                  :max="10000"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="NELM">
                <el-input-number
                  v-model="formData.namd_input.nelm"
                  :min="1"
                  :max="1000"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="NAMD Time Steps">
                <el-input-number
                  v-model="formData.namd_input.namdtime"
                  :min="1000"
                  :step="100000"
                />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Hole Dynamics">
                <el-switch v-model="formData.namd_input.lhole" />
              </el-form-item>
            </el-col>
            <el-col :span="16">
              <el-form-item label="Initial Bands (comma-separated, 1-based)">
                <el-input
                  v-model="namdInibandsStr"
                  placeholder="e.g. 1,2,3,4"
                />
              </el-form-item>
            </el-col>
          </el-row>
        </div>
      </el-card>

      <!-- Submit section -->
      <div class="submit-section">
        <el-button
          type="primary"
          size="large"
          :loading="submitting"
          @click="handleSubmit"
        >
          Submit Task
        </el-button>
      </div>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { QuestionFilled } from '@element-plus/icons-vue'
import PoscarUploader from '@/components/PoscarUploader.vue'
import StepSelector from '@/components/StepSelector.vue'
import { validatePoscar } from '@/api/structures'
import http from '@/api/http'
import type { ValidatePoscarResponse, NVTInput, NVEInput, SCFInput, PreNAMDInput, NAMDInput } from '@/api/types'

// SCF convergence threshold options (exponential steps)
const scfThrOptions = [1e-4, 1e-5, 1e-6, 1e-7, 1e-8]

// Step-to-input mapping (MUST be defined at top level, NOT inside watch)
const stepToInputMap: Record<string, string> = {
  nvt: 'nvt_input',
  nve: 'nve_input',
  scf: 'scf_input',
  pre_namd: 'prenamd_input',
  namd: 'namd_input'
}

const router = useRouter()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const poscarContent = ref('')
const poscarValidation = ref<ValidatePoscarResponse | null>(null)
const poscarVersion = ref(0) // Used to prevent race condition in validation

// --- Default input objects matching backend Pydantic models exactly ---

function createDefaultNvtInput(): NVTInput {
  return {
    kspacing: 0.04,
    md_thermostat: 'rescale_v',
    md_dt: 1.0,
    md_step: 1000,
    temp_begin: 300.0,
    temp_end: 300.0,
    scf_thr: 1e-6,
    parameters: ''
  }
}

function createDefaultNveInput(): NVEInput {
  return {
    kspacing: 0.04,
    md_dt: 1.0,
    md_step: 1000,
    scf_thr: 1e-6,
    parameters: ''
  }
}

function createDefaultScfInput(): SCFInput {
  return {
    kspacing: 0.04,
    scf_thr: 1e-6,
    scf_step: 1000,
    batch_size: 100,
    is_alle: false,
    parameters: ''
  }
}

function createDefaultPrenamdInput(): PreNAMDInput {
  return {
    bmin: 'VBM',
    bmax: 'CBM',
    md_dt: 1.0,
    adiabatic_rep: true,
    surface_hopping: 'DISH',
    adv: {
      reorder: false,
      alle: false,
      ikpt: 1,
      ispin: 1
    }
  }
}

function createDefaultNamdInput(): NAMDInput {
  return {
    md_dt: 1.0,
    adiabatic_rep: true,
    surface_hopping: 'DISH',
    nsample: 200,
    ntraj: 200,
    nelm: 10,
    namdtime: 1000000,
    temperature: 300.0,
    lhole: false,
    inibands: [1, 2, 3, 4]
  }
}

// Helper: stringify namd inibands for text input
const namdInibandsStr = computed({
  get: () => formData.namd_input.inibands.join(','),
  set: (val: string) => {
    formData.namd_input.inibands = val.split(',')
      .map(s => parseInt(s.trim(), 10))
      .filter(n => !isNaN(n))
  }
})

const formData = reactive<{
  steps: string[]
  method: 'namd' | 'n2amd'
  nvt_input: NVTInput
  nve_input: NVEInput
  scf_input: SCFInput
  prenamd_input: PreNAMDInput
  namd_input: NAMDInput
}>({
  steps: [],
  method: 'namd',
  nvt_input: createDefaultNvtInput(),
  nve_input: createDefaultNveInput(),
  scf_input: createDefaultScfInput(),
  prenamd_input: createDefaultPrenamdInput(),
  namd_input: createDefaultNamdInput()
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

// Watch steps changes to manage input objects
watch(
  () => formData.steps,
  (newSteps, oldSteps) => {
    // Reset input objects for newly selected steps
    for (const step of newSteps) {
      const inputKey = stepToInputMap[step]
      if (inputKey) {
        switch (inputKey) {
          case 'nvt_input':
            if (!formData.nvt_input || Object.keys(formData.nvt_input).length === 0) {
              formData.nvt_input = createDefaultNvtInput()
            }
            break
          case 'nve_input':
            if (!formData.nve_input || Object.keys(formData.nve_input).length === 0) {
              formData.nve_input = createDefaultNveInput()
            }
            break
          case 'scf_input':
            if (!formData.scf_input || Object.keys(formData.scf_input).length === 0) {
              formData.scf_input = createDefaultScfInput()
            }
            break
          case 'prenamd_input':
            if (!formData.prenamd_input || Object.keys(formData.prenamd_input).length === 0) {
              formData.prenamd_input = createDefaultPrenamdInput()
            }
            break
          case 'namd_input':
            if (!formData.namd_input || Object.keys(formData.namd_input).length === 0) {
              formData.namd_input = createDefaultNamdInput()
            }
            break
        }
      }
    }

    // Clear inputs for deselected steps
    const removedSteps = (oldSteps || []).filter(s => !newSteps.includes(s))
    for (const step of removedSteps) {
      const inputKey = stepToInputMap[step]
      if (inputKey === 'nvt_input') formData.nvt_input = createDefaultNvtInput()
      if (inputKey === 'nve_input') formData.nve_input = createDefaultNveInput()
      if (inputKey === 'scf_input') formData.scf_input = createDefaultScfInput()
      if (inputKey === 'prenamd_input') formData.prenamd_input = createDefaultPrenamdInput()
      if (inputKey === 'namd_input') formData.namd_input = createDefaultNamdInput()
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

async function handleSubmit(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

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

  // Validate at least one step selected (redundant but explicit)
  if (formData.steps.length === 0) {
    ElMessage.error('At least one step must be selected')
    return
  }

  // Validate NAMD step requires inibands
  if (formData.steps.includes('namd') && formData.namd_input.inibands.length === 0) {
    ElMessage.error('NAMD requires at least one initial band (inibands)')
    return
  }

  // Build submit payload matching backend InputT exactly
  const payload = {
    basic_input: {
      software: 'vasp' as const,
      plot: false
    },
    scheduler_config: {},
    steps: formData.steps,
    stru: poscarContent.value,
    stru_format: 'vasp',
    // Include inputs for selected steps
    ...(formData.steps.includes('nvt') && { nvt_input: formData.nvt_input }),
    ...(formData.steps.includes('nve') && { nve_input: formData.nve_input }),
    ...(formData.steps.includes('scf') && { scf_input: formData.scf_input }),
    ...(formData.steps.includes('pre_namd') && { prenamd_input: formData.prenamd_input }),
    ...(formData.steps.includes('namd') && { namd_input: formData.namd_input })
  }

  submitting.value = true
  try {
    const response = await http.post<string>(
      `/submit?method=${formData.method}`,
      payload
    )
    const taskId = response.data
    ElMessage.success(`Task submitted: ${taskId}`)
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

:deep(.el-input-number) {
  width: 100%;
}

:deep(.el-select) {
  width: 100%;
}

.disabled-radio-wrapper {
  display: inline-block;
}

:deep(.param-label) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

:deep(.param-help-icon) {
  font-size: 14px;
  color: var(--el-text-color-placeholder);
  cursor: help;
}
</style>
