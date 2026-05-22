/**
 * Composable for managing file selection state and batch download
 * in the task detail page.
 *
 * Extracted from TaskDetailPage.vue to reduce component complexity.
 */

import { reactive, computed, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { downloadZip, type ZipDownloadFileItem } from '@/api/tasks'
import type { JobFilesResponse, SubdirFilesResponse } from '@/api/types'

export function useFileSelection(
  taskId: Ref<string>,
  jobFiles: Ref<Map<string, JobFilesResponse>>,
  subdirFiles: Ref<Map<string, SubdirFilesResponse>>,
  loadSubdirFiles: (jobUuid: string, subdirName: string) => Promise<void>,
) {
  // Key: "${jobUuid}" for root files, "${jobUuid}/${subdir}" for subdir files.
  // Value: set of selected filenames in that location.
  const selectedFiles = reactive(new Map<string, Set<string>>())

  // Mutable download state exposed to the parent component.
  const downloadState = reactive({
    downloading: false,
    progress: -1, // -1 = preparing, 0..100 = transfer progress
  })

  function getSelectionKey(jobUuid: string, subdir?: string): string {
    return subdir ? `${jobUuid}/${subdir}` : jobUuid
  }

  function isFileSelected(jobUuid: string, filename: string, subdir?: string): boolean {
    const key = getSelectionKey(jobUuid, subdir)
    return selectedFiles.get(key)?.has(filename) ?? false
  }

  function toggleFileSelection(jobUuid: string, filename: string, subdir?: string): void {
    const key = getSelectionKey(jobUuid, subdir)
    if (!selectedFiles.has(key)) selectedFiles.set(key, new Set())
    const set = selectedFiles.get(key)!
    if (set.has(filename)) {
      set.delete(filename)
    } else {
      set.add(filename)
    }
  }

  function toggleGroupSelection(jobUuid: string, files: { name: string }[], subdir?: string): void {
    const key = getSelectionKey(jobUuid, subdir)
    if (!selectedFiles.has(key)) selectedFiles.set(key, new Set())
    const set = selectedFiles.get(key)!
    const allSelected = files.every(file => set.has(file.name))
    if (allSelected) {
      for (const file of files) set.delete(file.name)
    } else {
      for (const file of files) set.add(file.name)
    }
  }

  function isGroupAllSelected(jobUuid: string, files: { name: string }[], subdir?: string): boolean {
    const key = getSelectionKey(jobUuid, subdir)
    const set = selectedFiles.get(key)
    if (!set || files.length === 0) return false
    return files.every(file => set.has(file.name))
  }

  const totalSelectedCount = computed(() => {
    let count = 0
    for (const set of selectedFiles.values()) count += set.size
    return count
  })

  const totalSelectedSize = computed(() => {
    let total = 0
    for (const [key, filenames] of selectedFiles.entries()) {
      const parts = key.split('/')
      const jobUuid = parts[0]
      const subdir = parts.length > 1 ? parts.slice(1).join('/') : undefined
      if (subdir) {
        const files = subdirFiles.value.get(key)?.files ?? []
        for (const f of files) {
          if (filenames.has(f.name)) total += f.size
        }
      } else {
        const files = jobFiles.value.get(jobUuid)?.files ?? []
        for (const f of files) {
          if (filenames.has(f.name)) total += f.size
        }
      }
    }
    return total
  })

  function clearSelection(): void {
    selectedFiles.clear()
  }

  function isSdGroupAllSelected(jobUuid: string, subdirs: { name: string }[]): boolean {
    if (subdirs.length === 0) return false
    return subdirs.every(sd => {
      const files = subdirFiles.value.get(`${jobUuid}/${sd.name}`)?.files ?? []
      return files.length > 0 && isGroupAllSelected(jobUuid, files, sd.name)
    })
  }

  async function toggleSdGroupSelectAll(jobUuid: string, subdirs: { name: string }[]): Promise<void> {
    const allLoaded = subdirs.every(sd => subdirFiles.value.has(`${jobUuid}/${sd.name}`))
    if (!allLoaded) {
      await Promise.all(
        subdirs
          .filter(sd => !subdirFiles.value.has(`${jobUuid}/${sd.name}`))
          .map(sd => loadSubdirFiles(jobUuid, sd.name))
      )
    }
    const allSelected = isSdGroupAllSelected(jobUuid, subdirs)
    for (const sd of subdirs) {
      const files = subdirFiles.value.get(`${jobUuid}/${sd.name}`)?.files ?? []
      if (files.length === 0) continue
      const key = getSelectionKey(jobUuid, sd.name)
      if (!selectedFiles.has(key)) selectedFiles.set(key, new Set())
      const set = selectedFiles.get(key)!
      if (allSelected) {
        for (const f of files) set.delete(f.name)
      } else {
        for (const f of files) set.add(f.name)
      }
    }
  }

  async function toggleSubdirSelectAll(jobUuid: string, subdirName: string): Promise<void> {
    const key = `${jobUuid}/${subdirName}`
    if (!subdirFiles.value.has(key)) {
      await loadSubdirFiles(jobUuid, subdirName)
    }
    const files = subdirFiles.value.get(key)?.files ?? []
    if (files.length > 0) {
      toggleGroupSelection(jobUuid, files, subdirName)
    }
  }

  async function handleBatchDownload(): Promise<void> {
    const items: ZipDownloadFileItem[] = []
    for (const [key, filenames] of selectedFiles.entries()) {
      const parts = key.split('/')
      const jobUuid = parts[0]
      const subdir = parts.length > 1 ? parts.slice(1).join('/') : undefined
      for (const filename of filenames) {
        items.push({ job_uuid: jobUuid, filename, subdir })
      }
    }
    if (items.length === 0) return

    downloadState.downloading = true
    downloadState.progress = -1
    try {
      const blob = await downloadZip(taskId.value, items, (event) => {
        if (event.total && event.total > 0) {
          downloadState.progress = Math.round((event.loaded / event.total) * 100)
        } else {
          downloadState.progress = 0
        }
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `qdyn_files_${taskId.value.slice(0, 8)}.zip`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      ElMessage.success(`Downloaded ${items.length} files`)
      clearSelection()
    } catch {
      ElMessage.error('Failed to download files')
    } finally {
      downloadState.downloading = false
      downloadState.progress = -1
    }
  }

  return {
    selectedFiles,
    downloadState,
    isFileSelected,
    toggleFileSelection,
    toggleGroupSelection,
    isGroupAllSelected,
    totalSelectedCount,
    totalSelectedSize,
    clearSelection,
    isSdGroupAllSelected,
    toggleSdGroupSelectAll,
    toggleSubdirSelectAll,
    handleBatchDownload,
  }
}
