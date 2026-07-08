<template>
  <div class="task-detail-page">
    <!-- Loading skeleton -->
    <div v-if="loading && !task" class="skeleton-container">
      <el-skeleton :rows="8" animated />
    </div>

    <!-- Task detail content -->
    <div v-else-if="task" class="task-detail-content">
      <!-- Header -->
      <div class="detail-header">
        <el-button @click="goBack">
          <el-icon><ArrowLeft /></el-icon>
          Back
        </el-button>
        <div class="header-info">
          <div class="task-name-row">
            <template v-if="editingName">
              <el-input
                ref="nameInputRef"
                v-model="editNameValue"
                size="large"
                :maxlength="50"
                show-word-limit
                class="name-edit-input"
                @keyup.enter="saveTaskName"
                @keyup.escape="cancelEditName"
              />
              <el-button type="primary" size="small" @click="saveTaskName" :loading="savingName">Save</el-button>
              <el-button size="small" @click="cancelEditName">Cancel</el-button>
            </template>
            <template v-else>
              <h2 class="task-id" @click="startEditName" title="Click to rename">{{ taskDisplayName }}</h2>
              <el-icon class="edit-name-icon" @click="startEditName"><Edit /></el-icon>
            </template>
          </div>
          <StatusBadge :status="task.derived_status" />
          <el-tag
            v-if="task.prev_task_id"
            type="info"
            size="small"
            class="resume-tag"
          >
            Resumed from:
            <router-link
              :to="{ name: 'task-detail', params: { taskId: task.prev_task_id } }"
              class="resume-link"
            >
              {{ task.prev_task_id.length > 20
                ? task.prev_task_id.slice(0, 12) + '...' + task.prev_task_id.slice(-8)
                : task.prev_task_id }}
            </router-link>
          </el-tag>
        </div>
        <!-- Action buttons -->
        <div class="header-actions">
          <el-button
            v-if="taskStatus === 'STOPPED' || taskStatus === 'PAUSED'"
            type="success"
            plain
            :loading="continuing"
            @click="handleContinue"
          >
            Continue
          </el-button>
          <el-button
            v-if="hasRunningJobs"
            type="warning"
            plain
            :loading="stopping"
            @click="handleStop"
          >
            Stop
          </el-button>
          <el-button
            type="danger"
            plain
            :loading="deleting"
            @click="handleDelete"
          >
            Delete
          </el-button>
        </div>
      </div>

      <!-- 3D structure preview -->
      <el-card v-if="structurePreview" class="structure-card">
        <template #header>
          <span class="card-title">Structure Preview</span>
        </template>
        <StructureViewer
          :preview="structurePreview"
          height="350px"
        />
      </el-card>

      <!-- Workflow progress timeline -->
      <el-card class="timeline-card">
        <template #header>
          <span class="card-title">Workflow Progress</span>
        </template>
        <JobStepTimeline v-if="jobsStatus" :jobs="jobsStatus.jobs" />
        <el-empty v-else description="No job status available" />
      </el-card>

      <!-- Job status list -->
      <el-card class="jobs-card">
        <template #header>
          <span class="card-title">Job Status</span>
        </template>

        <el-table
          v-if="jobsStatus && jobsStatus.jobs.length > 0"
          ref="jobTableRef"
          :data="sortedJobs"
          row-key="uuid"
          stripe
          :expand-row-keys="expandedRowKeys"
          @expand-change="handleExpandChange"
        >
          <el-table-column prop="index" label="#" width="60" />
          <el-table-column label="Job Name" min-width="200">
            <template #default="{ row }">
              <span class="job-name-cell">{{ jobDisplayName(row.name) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="Status" width="120">
            <template #default="{ row }">
              <StatusBadge :status="row.derived_state" />
            </template>
          </el-table-column>
          <el-table-column prop="state" label="Raw State" width="150">
            <template #default="{ row }">
              <el-tag size="small" type="info">{{ row.state }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="Error" min-width="150">
            <template #default="{ row }">
              <el-text v-if="row.error" type="danger" truncated>
                {{ row.error }}
              </el-text>
              <el-button
                v-else-if="row.derived_state === 'FAILED' || row.derived_state === 'ERROR'"
                type="danger"
                link
                size="small"
                @click.stop="toggleJobError(row)"
              >
                {{ expandedErrors.has(row.uuid) ? 'Hide Error' : 'View Error' }}
              </el-button>
              <span v-else class="no-error">-</span>
            </template>
          </el-table-column>

          <!-- Expand row: delegated to JobExpandedRow -->
          <el-table-column type="expand">
            <template #default="{ row }">
              <JobExpandedRow
                :row="row"
                :task-id="taskId"
                :row-state="{
                  expandedError: expandedErrors.has(row.uuid),
                  errorLoading: errorLoading.has(row.uuid),
                  error: jobErrors.get(row.uuid),
                  progressLoading: progressLoading.has(row.uuid),
                  progress: jobProgress.get(row.uuid),
                  inputParamsLoading: inputParamsLoading.has(row.uuid),
                  inputParams: jobInputParams.get(row.uuid),
                  filesLoading: filesLoading.has(row.uuid),
                  files: jobFiles.get(row.uuid),
                }"
                :image-blob-urls="imageBlobUrls"
                :subdir-files="subdirFiles"
                :subdir-files-loading="subdirFilesLoading"
                :is-file-selected="isFileSelected"
                :is-group-all-selected="isGroupAllSelected"
                :is-sd-group-all-selected="isSdGroupAllSelected"
                @retry-error="retryJobError"
                @download-file="downloadFile"
                @load-subdir-files="loadSubdirFiles"
                @download-subdir-file="downloadSubdirFile"
                @toggle-file-selection="toggleFileSelection"
                @toggle-group-selection="toggleGroupSelection"
                @toggle-subdir-select-all="toggleSubdirSelectAll"
                @toggle-sd-group-select-all="toggleSdGroupSelectAll"
              />
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-if="!jobsStatus || jobsStatus.jobs.length === 0" description="No jobs found" />
      </el-card>
    </div>

    <!-- Error state -->
    <el-empty v-else description="Task not found">
      <el-button type="primary" @click="goBack">Go Back</el-button>
    </el-empty>

    <!-- Batch download floating bar -->
    <transition name="slide-up">
      <div v-if="totalSelectedCount > 0 || downloadState.downloading" class="batch-download-bar">
        <span v-if="downloadState.downloading && downloadState.progress < 0">
          Preparing archive...
        </span>
        <span v-else-if="downloadState.downloading && downloadState.progress >= 0">
          Downloading... {{ downloadState.progress }}%
        </span>
        <span v-else>
          {{ totalSelectedCount }} file{{ totalSelectedCount > 1 ? 's' : '' }} selected
          ({{ formatFileSize(totalSelectedSize) }})
        </span>
        <div class="batch-download-actions">
          <el-button size="small" :disabled="downloadState.downloading" @click="clearSelection">Clear</el-button>
          <el-button
            type="primary"
            size="small"
            :loading="downloadState.downloading"
            :disabled="downloadState.downloading"
            @click="handleBatchDownload"
          >
            <el-icon><Download /></el-icon>
            Download as ZIP
          </el-button>
        </div>
      </div>
    </transition>

  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onUnmounted, watch, type ComponentPublicInstance } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Download, Edit } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useTasksStore } from '@/stores/tasks'
import { useAuthStore } from '@/stores/auth'
import { fetchJobError, stopTask, continueTask, deleteTask, renameTask, getJobFiles, getJobFile, getSubdirFiles, getSubdirFile, getJobProgress, getJobInputParams } from '@/api/tasks'
import { adminStopTask, adminContinueTask, adminDeleteTask } from '@/api/admin'
import { getTaskStructurePreview } from '@/api/structures'
import { getTaskDisplayName } from '@/utils/task-display'
import { formatFileSize } from '@/utils/format'
import { PHASE_ORDER } from '@/constants/steps'
import { useFileSelection } from '@/composables/useFileSelection'
import { usePolling } from '@/composables/usePolling'
import StatusBadge from '@/components/StatusBadge.vue'
import JobStepTimeline from '@/components/JobStepTimeline.vue'
import JobExpandedRow from '@/components/JobExpandedRow.vue'
import StructureViewer from '@/components/StructureViewer.vue'
import type { JobStatusItem, JobErrorResponse, JobFilesResponse, JobProgressResponse, JobInputParamsResponse, SubdirFilesResponse, StructurePreviewPayload } from '@/api/types'

const route = useRoute()
const router = useRouter()
const tasksStore = useTasksStore()
const authStore = useAuthStore()

const task = computed(() => tasksStore.currentTask)
const jobsStatus = computed(() => tasksStore.currentJobsStatus)
const loading = computed(() => tasksStore.loading)


// Table ref for programmatic row expansion
const jobTableRef = ref<ComponentPublicInstance & { toggleRowExpansion: (row: JobStatusItem, expanded: boolean) => void } | null>(null)

// Explicitly tracked expand-row-keys so polling data refreshes do not collapse open rows
const expandedRowKeys = ref<string[]>([])

// Error expansion state
const expandedErrors = ref<Set<string>>(new Set())
const jobErrors = ref<Map<string, JobErrorResponse>>(new Map())
const errorLoading = ref<Set<string>>(new Set())

// Job progress, images, and files state
const jobProgress = ref<Map<string, JobProgressResponse>>(new Map())
const jobFiles = ref<Map<string, JobFilesResponse>>(new Map())
const jobInputParams = ref<Map<string, JobInputParamsResponse>>(new Map())
const imageBlobUrls = ref<Map<string, string>>(new Map())

// Subdirectory file state: keyed by "jobUuid/subdirName"
const subdirFiles = ref<Map<string, SubdirFilesResponse>>(new Map())
const subdirFilesLoading = ref<Set<string>>(new Set())

// Per-job loading states for expanded-row sections
const filesLoading = ref<Set<string>>(new Set())
const inputParamsLoading = ref<Set<string>>(new Set())
const progressLoading = ref<Set<string>>(new Set())

// Operation loading states
const stopping = ref(false)
const continuing = ref(false)
const deleting = ref(false)

const taskId = computed(() => route.params.taskId as string)

// loadSubdirFiles is defined here (before useFileSelection) because the
// composable needs it as a callback parameter.
async function loadSubdirFiles(jobUuid: string, subdirName: string): Promise<void> {
  const key = `${jobUuid}/${subdirName}`
  if (subdirFiles.value.has(key)) return

  subdirFilesLoading.value.add(key)
  subdirFilesLoading.value = new Set(subdirFilesLoading.value)
  try {
    const result = await getSubdirFiles(taskId.value, jobUuid, subdirName)
    subdirFiles.value.set(key, result)
    subdirFiles.value = new Map(subdirFiles.value)
  } catch {
    // Silently ignore
  } finally {
    subdirFilesLoading.value.delete(key)
    subdirFilesLoading.value = new Set(subdirFilesLoading.value)
  }
}

// File selection + batch download (delegated to composable)
const {
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
} = useFileSelection(taskId, jobFiles, subdirFiles, loadSubdirFiles)

// Polling (delegated to composable)
const { start: startPolling, stop: stopPolling } = usePolling(
  async () => {
    const result = await tasksStore.fetchJobsStatusSilent(taskId.value)
    await refreshJobExtras()
    const activeStates = new Set(['RUNNING', 'PENDING'])
    const hasActive = result.jobs.some(
      job => job.derived_state !== null && activeStates.has(job.derived_state)
    )
    if (!hasActive) {
      stopPolling()
    }
  },
  30_000,
  () => hasRunningJobs.value,
)

const truncatedTaskId = computed((): string => {
  const id = taskId.value
  if (id.length <= 20) return id
  return `${id.slice(0, 12)}...${id.slice(-8)}`
})

/** Task display name: task_name > formula > truncated task_id */
const taskDisplayName = computed((): string => {
  if (task.value) {
    return getTaskDisplayName(task.value)
  }
  return truncatedTaskId.value
})

// Inline task name editing
const editingName = ref(false)
const editNameValue = ref('')
const savingName = ref(false)
const nameInputRef = ref<InstanceType<typeof import('element-plus')['ElInput']> | null>(null)

function startEditName(): void {
  editNameValue.value = task.value?.task_name || ''
  editingName.value = true
  nextTick(() => nameInputRef.value?.focus())
}

function cancelEditName(): void {
  editingName.value = false
}

async function saveTaskName(): Promise<void> {
  const name = editNameValue.value.trim() || null
  savingName.value = true
  try {
    await renameTask(taskId.value, name)
    // Update the local store so display refreshes immediately
    if (tasksStore.currentTask) {
      tasksStore.currentTask = { ...tasksStore.currentTask, task_name: name }
    }
    editingName.value = false
  } catch {
    ElMessage.error('Failed to rename task')
  } finally {
    savingName.value = false
  }
}

/** Structure preview data (fetched on-demand from dedicated endpoint) */
const structurePreview = ref<StructurePreviewPayload | null>(null)
let previewRequestId = 0 // monotonic counter to discard stale responses on route change

async function fetchStructurePreview() {
  const myRequestId = ++previewRequestId
  try {
    const result = await getTaskStructurePreview(taskId.value)
    if (previewRequestId !== myRequestId) return // stale — route changed during fetch
    structurePreview.value = result
  } catch {
    if (previewRequestId !== myRequestId) return
    // Non-critical: preview unavailable does not block task detail
    structurePreview.value = null
  }
}

function jobDisplayName(name: string): string {
  if (name.toLowerCase().includes('cat_canac')) return 'CA-NAC Aggregation'
  return name
}

function getPhaseFromName(name: string): number {
  const lower = name.toLowerCase()
  // Fused priority match (before scf/namd substring would match)
  if (lower.includes('fused')) return PHASE_ORDER['fused_scf_prenamd']
  if (lower.includes('cat_canac')) return PHASE_ORDER['fused_cat']
  // Job names like "nvt_0", "nve_0", "scf_0", "pre_namd_0", "namd_0"
  // Extract the step type by removing the trailing "_<index>"
  const lastUnderscore = name.lastIndexOf('_')
  const stepType = lastUnderscore > 0 ? name.slice(0, lastUnderscore) : name
  return PHASE_ORDER[stepType] ?? 999
}

const sortedJobs = computed((): JobStatusItem[] => {
  if (!jobsStatus.value?.jobs) return []
  return [...jobsStatus.value.jobs].sort((a, b) => {
    const phaseA = getPhaseFromName(a.name)
    const phaseB = getPhaseFromName(b.name)
    if (phaseA !== phaseB) return phaseA - phaseB
    return a.index - b.index
  })
})

const taskStatus = computed(() => task.value?.derived_status ?? null)

// Whether any job is in a running/waiting state
const hasRunningJobs = computed((): boolean => {
  if (!jobsStatus.value?.jobs) return false
  const activeStates = new Set(['RUNNING', 'PENDING'])
  return jobsStatus.value.jobs.some(
    job => job.derived_state !== null && activeStates.has(job.derived_state)
  )
})

// ============================================
// Lifecycle
// ============================================

async function loadTaskData(): Promise<void> {
  // Clear stale state from previous task
  jobFiles.value.clear()
  jobProgress.value.clear()
  jobInputParams.value.clear()
  expandedErrors.value.clear()
  jobErrors.value.clear()
  subdirFiles.value.clear()
  subdirFilesLoading.value.clear()
  filesLoading.value.clear()
  inputParamsLoading.value.clear()
  progressLoading.value.clear()
  clearSelection()
  expandedRowKeys.value = []
  for (const url of imageBlobUrls.value.values()) {
    URL.revokeObjectURL(url)
  }
  imageBlobUrls.value.clear()

  try {
    await tasksStore.fetchTaskDetail(taskId.value)
    await refreshJobExtras()
  } catch {
    // Error is handled by store
  }
}

onMounted(async () => {
  await loadTaskData()
  fetchStructurePreview()  // fire-and-forget: non-blocking
  startPolling()
})

// Reload when navigating between tasks (e.g. "Resumed from" link)
watch(taskId, async () => {
  stopPolling()
  previewRequestId++ // invalidate any in-flight preview request
  structurePreview.value = null
  await loadTaskData()
  fetchStructurePreview()
  startPolling()
})

onUnmounted(() => {
  // Release all blob URLs to free memory
  for (const url of imageBlobUrls.value.values()) {
    URL.revokeObjectURL(url)
  }
  imageBlobUrls.value.clear()
  tasksStore.clearCurrentTask()
})

// ============================================
// Job error detail
// ============================================

async function toggleJobError(job: JobStatusItem): Promise<void> {
  if (expandedErrors.value.has(job.uuid)) {
    expandedErrors.value.delete(job.uuid)
    // Force reactivity on Set
    expandedErrors.value = new Set(expandedErrors.value)
    return
  }

  expandedErrors.value.add(job.uuid)
  expandedErrors.value = new Set(expandedErrors.value)

  // Expand the table row so that the error detail is visible
  jobTableRef.value?.toggleRowExpansion(job, true)

  // Fetch error details if not already loaded
  if (!jobErrors.value.has(job.uuid)) {
    await loadJobError(job)
  }
}

async function loadJobError(job: JobStatusItem, force = false): Promise<void> {
  // Force option bypasses cache and retries even if failed before
  if (!force && jobErrors.value.has(job.uuid)) {
    return
  }

  errorLoading.value.add(job.uuid)
  errorLoading.value = new Set(errorLoading.value)

  try {
    const errorDetail = await fetchJobError(taskId.value, job.uuid)
    jobErrors.value.set(job.uuid, errorDetail)
    jobErrors.value = new Map(jobErrors.value)
  } catch {
    // Don't cache failed requests - allow retry on next click
  } finally {
    errorLoading.value.delete(job.uuid)
    errorLoading.value = new Set(errorLoading.value)
  }
}

async function retryJobError(job: JobStatusItem): Promise<void> {
  // Force retry by clearing cache and loading again
  jobErrors.value.delete(job.uuid)
  jobErrors.value = new Map(jobErrors.value)

  // Ensure the error is expanded
  if (!expandedErrors.value.has(job.uuid)) {
    expandedErrors.value.add(job.uuid)
    expandedErrors.value = new Set(expandedErrors.value)
  }

  await loadJobError(job, true)
}

// ============================================
// Job progress, images, and files
// ============================================

async function loadJobProgress(job: JobStatusItem, showLoading = true): Promise<void> {
  if (showLoading) {
    progressLoading.value.add(job.uuid)
    progressLoading.value = new Set(progressLoading.value)
  }
  try {
    const progress = await getJobProgress(taskId.value, job.uuid)
    jobProgress.value.set(job.uuid, progress)
    jobProgress.value = new Map(jobProgress.value)
  } catch {
    // Silently ignore progress fetch errors
  } finally {
    if (showLoading) {
      progressLoading.value.delete(job.uuid)
      progressLoading.value = new Set(progressLoading.value)
    }
  }
}


async function loadJobFiles(job: JobStatusItem): Promise<void> {
  if (jobFiles.value.has(job.uuid)) return
  filesLoading.value.add(job.uuid)
  filesLoading.value = new Set(filesLoading.value)
  try {
    const files = await getJobFiles(taskId.value, job.uuid)
    jobFiles.value.set(job.uuid, files)
    jobFiles.value = new Map(jobFiles.value)
    // Auto-load blob URLs for image files
    for (const file of files.files) {
      if (file.category === 'image') {
        loadFileBlobUrl(job.uuid, file.name)
      }
    }
  } catch {
    // Silently ignore
  } finally {
    filesLoading.value.delete(job.uuid)
    filesLoading.value = new Set(filesLoading.value)
  }
}

function downloadSubdirFile(job: JobStatusItem, subdir: string, filename: string): void {
  getSubdirFile(taskId.value, job.uuid, subdir, filename).then(blob => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }).catch(() => {
    ElMessage.error(`Failed to download ${subdir}/${filename}`)
  })
}


async function loadFileBlobUrl(jobUuid: string, fileName: string): Promise<void> {
  const key = `${jobUuid}/${fileName}`
  if (imageBlobUrls.value.has(key)) return
  try {
    const blob = await getJobFile(taskId.value, jobUuid, fileName)
    const blobUrl = URL.createObjectURL(blob)
    imageBlobUrls.value.set(key, blobUrl)
    imageBlobUrls.value = new Map(imageBlobUrls.value)
  } catch {
    // Silently ignore
  }
}

async function loadJobInputParams(job: JobStatusItem): Promise<void> {
  // Allow retry if previously cached as unavailable (run_dir may not have existed yet)
  const cached = jobInputParams.value.get(job.uuid)
  if (cached?.available) return
  inputParamsLoading.value.add(job.uuid)
  inputParamsLoading.value = new Set(inputParamsLoading.value)
  try {
    const params = await getJobInputParams(taskId.value, job.uuid)
    jobInputParams.value.set(job.uuid, params)
    jobInputParams.value = new Map(jobInputParams.value)
  } catch {
    // Silently ignore
  } finally {
    inputParamsLoading.value.delete(job.uuid)
    inputParamsLoading.value = new Set(inputParamsLoading.value)
  }
}

function downloadFile(job: JobStatusItem, filename: string): void {
  getJobFile(taskId.value, job.uuid, filename).then(blob => {
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }).catch(() => {
    ElMessage.error(`Failed to download ${filename}`)
  })
}

// Fetch progress only for RUNNING jobs.
// COMPLETED job progress is loaded on-demand when a row is expanded.
async function refreshJobExtras(): Promise<void> {
  if (!jobsStatus.value?.jobs) return
  const promises: Promise<void>[] = []
  for (const job of jobsStatus.value.jobs) {
    if (job.derived_state === 'RUNNING') {
      // Pass showLoading=false so background polling does not flash spinners
      promises.push(loadJobProgress(job, false))
    }
  }
  await Promise.allSettled(promises)
}

// ============================================
// Stop and Delete operations
// ============================================

async function handleStop(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      'All running computations will be cancelled. Results from completed steps will be preserved.',
      'Confirm Stop',
      {
        confirmButtonText: 'Stop',
        cancelButtonText: 'Cancel',
        type: 'warning'
      }
    )
  } catch {
    return // User cancelled
  }

  stopping.value = true
  try {
    const result = authStore.isAdmin
      ? await adminStopTask(taskId.value)
      : await stopTask(taskId.value)
    if (result.failed.length > 0) {
      const failedDetails = result.failed.map(f => `${f.uuid.slice(0, 8)}: ${f.error}`).join(', ')
      ElMessage.warning(`Some jobs failed to stop: ${failedDetails}`)
    } else {
      ElMessage.success('Task stopped successfully')
    }
    // Refresh job status
    await tasksStore.fetchJobsStatus(taskId.value)
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to stop task'
    ElMessage.error(message)
  } finally {
    stopping.value = false
  }
}

async function handleContinue(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      'Paused or stopped jobs will be re-queued. Completed jobs remain unchanged.',
      'Confirm Continue',
      {
        confirmButtonText: 'Continue',
        cancelButtonText: 'Cancel',
        type: 'info'
      }
    )
  } catch {
    return // User cancelled
  }

  continuing.value = true
  try {
    const result = authStore.isAdmin
      ? await adminContinueTask(taskId.value)
      : await continueTask(taskId.value)
    if (result.failed.length > 0) {
      const failedDetails = result.failed.map(f => `${f.uuid.slice(0, 8)}: ${f.error}`).join(', ')
      ElMessage.warning(`Some jobs failed to resume: ${failedDetails}`)
    } else {
      ElMessage.success('Task resumed successfully')
    }
    await tasksStore.fetchTaskDetail(taskId.value)
    await refreshJobExtras()
    startPolling()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to resume task'
    ElMessage.error(message)
  } finally {
    continuing.value = false
  }
}

async function handleDelete(): Promise<void> {
  try {
    await ElMessageBox.confirm(
      'All running computations will be cancelled and the task record will be removed.',
      'Confirm Delete',
      {
        confirmButtonText: 'Delete',
        cancelButtonText: 'Cancel',
        type: 'error'
      }
    )
  } catch {
    return // User cancelled
  }

  deleting.value = true
  try {
    if (authStore.isAdmin) {
      await adminDeleteTask(taskId.value)
    } else {
      await deleteTask(taskId.value)
    }
    ElMessage.success('Task deleted')
    // After deletion, go to the list the user came from (preserving filters
    // like ?owner=xxx via returnTo). Use push (not back) so we don't return
    // to the now-deleted task's detail.
    const returnTo = route.query.returnTo
    if (typeof returnTo === 'string' && returnTo) {
      router.push(returnTo)
    } else {
      router.push({ name: authStore.isAdmin ? 'admin-tasks' : 'task-list' })
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to delete task'
    ElMessage.error(message)
  } finally {
    deleting.value = false
  }
}

// Watch for jobsStatus changes to manage polling lifecycle
watch(hasRunningJobs, (newValue) => {
  if (newValue) {
    startPolling()
  } else {
    stopPolling()
  }
})

// ============================================
// Navigation
// ============================================

function goBack(): void {
  // Prefer an explicit returnTo query param (set by the calling list page)
  // so the user returns to the exact list they came from, preserving any
  // filter such as ?owner=xxx. Fall back to browser history back, then to
  // the appropriate list route when there is no history (e.g. the detail
  // page was opened directly via URL).
  const returnTo = route.query.returnTo
  if (typeof returnTo === 'string' && returnTo) {
    router.push(returnTo)
    return
  }
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push({ name: authStore.isAdmin ? 'admin-tasks' : 'task-list' })
  }
}

function isScfJob(job: JobStatusItem): boolean {
  const name = job.name.toLowerCase()
  return name.startsWith('scf_') || name.includes('fused')
}

function handleExpandChange(row: JobStatusItem, expandedRows: JobStatusItem[]): void {
  // Sync expandedRowKeys so the explicit binding survives data refreshes caused by polling
  expandedRowKeys.value = expandedRows.map(r => r.uuid)

  const isExpanded = expandedRows.some(r => r.uuid === row.uuid)
  if (!isExpanded) return

  // Load files and input params on demand when any job row is expanded
  loadJobFiles(row)
  loadJobInputParams(row)

  // Load progress on expand for:
  // - COMPLETED jobs (final state after RUNNING -> COMPLETED transition)
  // - SCF jobs in non-PENDING states (so failed frame details are visible)
  if (row.derived_state === 'COMPLETED' ||
      (isScfJob(row) && row.derived_state && row.derived_state !== 'PENDING')) {
    loadJobProgress(row)
  }

  // Load image list on demand when a COMPLETED job row is expanded.
  // Image blobs are now loaded automatically by loadJobFiles() for image-category files
}
</script>

<style scoped>
.task-detail-page {
  padding: var(--space-6);
  max-width: 1000px;
  margin: 0 auto;
}

.skeleton-container {
  padding: var(--space-6);
}

.detail-header {
  display: flex;
  align-items: center;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.header-info {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  flex: 1;
}

.header-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

.task-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.task-id {
  margin: 0;
  font: var(--text-h2);
  cursor: pointer;
}

.task-id:hover {
  color: var(--brand-primary);
}

.edit-name-icon {
  cursor: pointer;
  color: var(--fg-tertiary);
  font-size: var(--fs-14);
}

.edit-name-icon:hover {
  color: var(--brand-primary);
}

.name-edit-input {
  width: 300px;
}

.card-title {
  font: var(--text-h3);
}

.structure-card {
  margin-bottom: var(--space-6);
}

.timeline-card {
  margin-bottom: var(--space-6);
}

.jobs-card {
  margin-bottom: var(--space-6);
}

/* Job name column in the job table */
.jobs-card :deep(.el-table) .job-name-cell {
  font-family: var(--font-mono);
  font-size: var(--fs-13);
}

.no-error {
  color: var(--fg-placeholder);
}

.resume-tag {
  margin-left: var(--space-2);
}

.resume-link {
  color: var(--brand-primary);
  text-decoration: none;
  margin-left: var(--space-1);
  font-family: var(--font-mono);
  font-size: var(--fs-12);
}

.resume-link:hover {
  text-decoration: underline;
}


.batch-download-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: 12px 24px;
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-lighter);
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.1);
}

.batch-download-actions {
  display: flex;
  gap: var(--space-2);
  flex-shrink: 0;
}

.slide-up-enter-active,
.slide-up-leave-active {
  transition: transform 0.2s ease, opacity 0.2s ease;
}

.slide-up-enter-from,
.slide-up-leave-to {
  transform: translateY(100%);
  opacity: 0;
}
</style>
