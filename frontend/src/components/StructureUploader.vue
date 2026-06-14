<template>
  <div class="structure-uploader-wrap">
    <div class="format-row">
      <span class="format-label">Format</span>
      <FormatSelect
        :model-value="format"
        :options="STRUCTURE_FORMAT_OPTIONS"
        placeholder="Select format"
        @update:model-value="(val: string) => emit('update:format', val)"
      />
    </div>

    <div
      class="structure-uploader"
      :class="{ 'is-dragover': isDragover }"
      @dragenter.prevent="handleDragEnter"
      @dragover.prevent="handleDragOver"
      @dragleave.prevent="handleDragLeave"
      @drop.prevent="handleDrop"
      @click="triggerFileInput"
    >
      <input
        ref="fileInputRef"
        type="file"
        accept="*/*"
        hidden
        @change="handleFileChange"
      />

      <div v-if="!fileName" class="upload-prompt">
        <el-icon class="upload-icon"><Upload /></el-icon>
        <div class="upload-text">
          <span>Drag structure file here or</span>
          <el-button type="primary" link>click to upload</el-button>
        </div>
        <div class="upload-hint">
          {{ uploadHint }}
        </div>
      </div>

      <div v-else class="upload-success">
        <el-icon class="success-icon"><Document /></el-icon>
        <div class="file-info">
          <span class="file-name">{{ fileName }}</span>
          <el-button
            type="danger"
            link
            size="small"
            @click.stop="clearFile"
          >
            Clear
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { Upload, Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import FormatSelect, { type FormatOption } from './FormatSelect.vue'

/**
 * Single-frame structure upload options.
 *
 * The value is the ASE `format=` string passed to the backend `read_stru()`.
 * This value domain is distinct from the trajectory uploader's options
 * (see TrajectoryUploader.vue) and must not be shared.
 */
const STRUCTURE_FORMAT_OPTIONS: FormatOption[] = [
  { label: 'VASP (POSCAR)', value: 'vasp' },
  { label: 'CIF', value: 'cif' },
  { label: 'extxyz', value: 'extxyz' },
  { label: 'OpenMX (.dat)', value: 'openmx-dat' },
]

const props = defineProps<{
  format: string
}>()

const emit = defineEmits<{
  (e: 'file-loaded', content: string, format: string): void
  (e: 'update:format', value: string): void
  (e: 'clear'): void
}>()

const fileInputRef = ref<HTMLInputElement | null>(null)
const isDragover = ref(false)
const fileName = ref('')
const currentFileToken = ref<string | null>(null) // Track current file to prevent race condition

const uploadHint = computed((): string => {
  switch (props.format) {
    case 'vasp':
      return 'Supports POSCAR / CONTCAR / .vasp'
    case 'cif':
      return 'Supports .cif'
    case 'extxyz':
      return 'Supports .extxyz (with cell)'
    case 'openmx-dat':
      return 'Supports OpenMX .dat'
    default:
      return 'Select a format above, then drop a structure file'
  }
})

function triggerFileInput(): void {
  fileInputRef.value?.click()
}

function handleDragEnter(): void {
  isDragover.value = true
}

function handleDragOver(): void {
  isDragover.value = true
}

function handleDragLeave(): void {
  isDragover.value = false
}

function handleDrop(event: DragEvent): void {
  isDragover.value = false

  const files = event.dataTransfer?.files
  if (!files || files.length === 0) return

  const file = files[0]
  processFile(file)
}

function handleFileChange(event: Event): void {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (!files || files.length === 0) return

  const file = files[0]
  processFile(file)
}

function processFile(file: File): void {
  // Generate a unique token for this file to prevent race conditions
  const fileToken = Date.now().toString()
  currentFileToken.value = fileToken

  if (!isValidStructureFile(file)) {
    ElMessage.error('Please upload a non-empty structure file')
    // Clear local state immediately for invalid files
    fileName.value = ''
    if (fileInputRef.value) {
      fileInputRef.value.value = ''
    }
    emit('clear')
    return
  }

  const reader = new FileReader()
  reader.onload = (e): void => {
    // Only process if this is still the current file
    if (currentFileToken.value !== fileToken) {
      return // This is an outdated file read
    }

    const content = e.target?.result as string
    if (!content || content.trim().length === 0) {
      ElMessage.error('File is empty')
      // Clear local state immediately for empty files
      fileName.value = ''
      if (fileInputRef.value) {
        fileInputRef.value.value = ''
      }
      emit('clear')
      return
    }

    fileName.value = file.name
    emit('file-loaded', content, props.format)
    ElMessage.success('Structure file loaded successfully')
  }

  reader.onerror = (): void => {
    // Only show error if this is still the current file
    if (currentFileToken.value === fileToken) {
      ElMessage.error('Failed to read file')
      // Clear local state immediately for read errors
      fileName.value = ''
      if (fileInputRef.value) {
        fileInputRef.value.value = ''
      }
      emit('clear')
    }
  }

  reader.readAsText(file)
}

// Format correctness is validated server-side per the selected format,
// so only coarse-filter here: reject empty files; accept text-like or
// extensionless files (browsers report empty type for POSCAR/.vasp/.dat).
function isValidStructureFile(file: File): boolean {
  if (file.size === 0) return false
  return true
}

function clearFile(): void {
  fileName.value = ''
  currentFileToken.value = null // Invalidate any pending file reads
  if (fileInputRef.value) {
    fileInputRef.value.value = ''
  }
  emit('clear')
}
</script>

<style scoped>
.structure-uploader-wrap {
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

.structure-uploader {
  border: 2px dashed var(--border-default);
  border-radius: var(--radius-lg);
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  transition: border-color var(--dur-base) var(--ease-standard),
              background-color var(--dur-base) var(--ease-standard);
  background-color: var(--bg-surface);
}

.structure-uploader:hover {
  border-color: var(--brand-primary);
  background-color: var(--bg-surface-alt);
}

.structure-uploader.is-dragover {
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

.upload-success {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-3);
}

.success-icon {
  font-size: 40px;
  color: var(--success-fg);
}

.file-info {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.file-name {
  font: var(--text-body-strong);
  font-family: var(--font-mono);
  color: var(--fg-primary);
}
</style>
