<template>
  <div
    class="poscar-uploader"
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
        <span>Drag POSCAR file here or</span>
        <el-button type="primary" link>click to upload</el-button>
      </div>
      <div class="upload-hint">
        Supports .poscar, .vasp, or POSCAR format
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
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Upload, Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const emit = defineEmits<{
  (e: 'file-loaded', content: string): void
  (e: 'clear'): void
}>()

const fileInputRef = ref<HTMLInputElement | null>(null)
const isDragover = ref(false)
const fileName = ref('')
const currentFileToken = ref<string | null>(null) // Track current file to prevent race condition

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

  if (!isValidPoscarFile(file)) {
    ElMessage.error('Please upload a valid POSCAR file')
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
    emit('file-loaded', content)
    ElMessage.success('POSCAR file loaded successfully')
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

function isValidPoscarFile(file: File): boolean {
  const validExtensions = ['.poscar', '.vasp']
  const validNames = ['poscar', 'contcar']
  const name = file.name.toLowerCase()

  // Accept known POSCAR extensions or filenames
  if (validExtensions.some(ext => name.endsWith(ext))) return true
  if (validNames.some(n => name.startsWith(n))) return true
  // Accept text files
  if (file.type.startsWith('text/')) return true
  // Accept files with no extension (browsers report empty type for
  // extensionless files like "POSCAR") — backend validates content
  if (!name.includes('.') || file.type === '') return true

  return false
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
.poscar-uploader {
  border: 2px dashed var(--el-border-color);
  border-radius: 8px;
  padding: 40px 20px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  background-color: var(--el-fill-color-blank);
}

.poscar-uploader:hover {
  border-color: var(--el-color-primary);
  background-color: var(--el-fill-color-light);
}

.poscar-uploader.is-dragover {
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

.upload-success {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.success-icon {
  font-size: 40px;
  color: var(--el-color-success);
}

.file-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-name {
  font-weight: 500;
  color: var(--el-text-color-primary);
}
</style>
