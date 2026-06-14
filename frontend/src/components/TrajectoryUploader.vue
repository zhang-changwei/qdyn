<template>
  <div class="traj-uploader-wrap">
    <div class="format-row">
      <span class="format-label">Format</span>
      <FormatSelect
        :model-value="format"
        :options="TRAJECTORY_FORMAT_OPTIONS"
        placeholder="Select format"
        @update:model-value="(val: string) => emit('update:format', val)"
      />
    </div>

    <div
      class="traj-uploader"
      :class="{ 'is-dragover': trajDragover }"
      @dragenter.prevent="trajDragover = true"
      @dragover.prevent="trajDragover = true"
      @dragleave.prevent="trajDragover = false"
      @drop.prevent="handleTrajDrop"
      @click="status === 'idle' && triggerTrajInput()"
    >
      <input
        ref="trajInputRef"
        type="file"
        hidden
        @change="handleTrajFileChange"
      />

      <!-- idle state -->
      <div v-if="status === 'idle'" class="upload-prompt">
        <el-icon class="upload-icon" :size="40"><Upload /></el-icon>
        <div class="upload-text">
          <span>Drag trajectory file here or </span>
          <el-button type="primary" link>click to upload</el-button>
        </div>
        <div class="upload-hint">
          {{ uploadHint }}
        </div>
      </div>

      <!-- hashing / checking / uploading / done / error -->
      <div v-else class="traj-status-area" @click.stop>
        <div class="traj-file-info">
          <el-icon><Document /></el-icon>
          <span class="traj-file-name">{{ fileName }}</span>
          <span class="traj-file-size">({{ formatFileSize(fileSize) }})</span>
          <el-button
            v-if="status !== 'uploading'"
            type="danger"
            link
            @click.stop="emit('clear')"
          >
            Remove
          </el-button>
        </div>

        <!-- hashing progress -->
        <div v-if="status === 'hashing'" class="traj-progress-row">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>Calculating file hash...</span>
          <el-progress
            :percentage="hashProgress"
            :show-text="true"
            :stroke-width="8"
            style="flex: 1; margin-left: 8px;"
          />
        </div>

        <!-- checking server -->
        <div v-if="status === 'checking'" class="traj-progress-row">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span>Checking server...</span>
        </div>

        <!-- uploading progress -->
        <div v-if="status === 'uploading'" class="traj-progress-row">
          <span>Uploading...</span>
          <el-progress
            :percentage="uploadProgress"
            :show-text="true"
            :stroke-width="8"
            status="warning"
            style="flex: 1; margin-left: 8px;"
          />
        </div>

        <!-- done -->
        <div v-if="status === 'done'" class="traj-done-area">
          <div class="traj-progress-row traj-done">
            <el-icon color="var(--el-color-success)"><SuccessFilled /></el-icon>
            <span>{{ skippedUpload ? 'File already on server' : 'Upload complete' }}</span>
          </div>
          <div v-if="summary" class="traj-summary">
            {{ summary.formula }} · {{ summary.num_atoms }} atoms{{ summary.num_frames ? ` · ${summary.num_frames} frames` : '' }}
          </div>
          <div class="traj-hash-display">
            MD5: <code>{{ hash }}</code>
          </div>
        </div>

        <!-- error -->
        <div v-if="status === 'error'" class="traj-progress-row traj-error">
          <el-icon color="var(--el-color-danger)"><CircleClose /></el-icon>
          <span>{{ errorMessage }}</span>
          <el-button type="primary" link @click.stop="emit('retry')">Retry</el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Upload, Document, Loading, SuccessFilled, CircleClose } from '@element-plus/icons-vue'
import { formatFileSize } from '@/utils/format'
import FormatSelect, { type FormatOption } from './FormatSelect.vue'

type TrajStatus = 'idle' | 'hashing' | 'checking' | 'uploading' | 'done' | 'error'

/**
 * Trajectory upload options.
 *
 * The value is the ASE trajectory `format=` string passed to the backend
 * `read_strus()`. This value domain is distinct from the single-frame
 * structure uploader's options (see StructureUploader.vue) and must not be
 * shared. In particular VASP trajectory is `vasp-xdatcar` — never bare `vasp`,
 * which would read only a single frame.
 */
const TRAJECTORY_FORMAT_OPTIONS: FormatOption[] = [
  { label: 'VASP (XDATCAR)', value: 'vasp-xdatcar' },
  { label: 'extxyz', value: 'extxyz' },
  { label: 'OpenMX (.md)', value: 'openmx-md' },
]

const props = defineProps<{
  status: TrajStatus
  hash: string
  fileName: string
  fileSize: number
  hashProgress: number
  uploadProgress: number
  skippedUpload: boolean
  summary: { formula: string; num_atoms: number; num_frames?: number } | null
  errorMessage: string
  format: string
}>()

const emit = defineEmits<{
  'file-selected': [file: File]
  'update:format': [value: string]
  'clear': []
  'retry': []
}>()

const uploadHint = computed((): string => {
  switch (props.format) {
    case 'vasp-xdatcar':
      return 'Supports XDATCAR'
    case 'extxyz':
      return 'Supports multi-frame .extxyz (with cell)'
    case 'openmx-md':
      return 'Supports OpenMX .md'
    default:
      return 'Select a format above, then drop a trajectory file'
  }
})

// Pure UI state — safe to lose on v-if unmount
const trajInputRef = ref<HTMLInputElement>()
const trajDragover = ref(false)

function triggerTrajInput(): void {
  trajInputRef.value?.click()
}

function handleTrajDrop(e: DragEvent): void {
  trajDragover.value = false
  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    emit('file-selected', files[0])
  }
}

function handleTrajFileChange(e: Event): void {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    emit('file-selected', input.files[0])
  }
  // Reset input value so selecting the same file again triggers change
  input.value = ''
}
</script>

<style scoped>
/* Trajectory uploader — visually matched to StructureUploader */
.traj-uploader-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.format-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.format-label {
  font: var(--text-body-strong);
  color: var(--fg-secondary);
}

.traj-uploader {
  border: 2px dashed var(--border-default);
  border-radius: var(--radius-lg);
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color var(--dur-base) var(--ease-standard),
              background-color var(--dur-base) var(--ease-standard);
  background-color: var(--bg-surface);
}

.traj-uploader:hover {
  border-color: var(--brand-primary);
  background-color: var(--bg-surface-alt);
}

.traj-uploader.is-dragover {
  border-color: var(--brand-primary);
  background-color: var(--brand-primary-soft);
}

.upload-prompt {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
}

.upload-icon {
  font-size: 48px;
  color: var(--fg-placeholder);
}

.upload-text {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  color: var(--fg-tertiary);
}

.upload-hint {
  font-size: var(--fs-12);
  color: var(--fg-placeholder);
}

.traj-status-area {
  cursor: default;
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.traj-file-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font: var(--text-body);
}

.traj-file-name {
  font: var(--text-body-strong);
  font-family: var(--font-mono);
}

.traj-file-size {
  color: var(--fg-tertiary);
}

.traj-progress-row {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  font: var(--text-small);
}

.traj-done {
  color: var(--success-fg);
}

.traj-error {
  color: var(--danger-fg);
}

.traj-done-area {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.traj-summary {
  font: var(--text-body-strong);
  color: var(--fg-primary);
}

.traj-hash-display {
  font: var(--text-caption);
  color: var(--fg-tertiary);
}

.traj-hash-display code {
  font-family: var(--font-mono);
  background: var(--bg-surface-alt);
  padding: 1px 4px;
  border-radius: var(--radius-sm);
}
</style>
