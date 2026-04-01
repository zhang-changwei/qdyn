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
          <h2 class="task-id">Task: {{ truncatedTaskId }}</h2>
          <StatusBadge :status="task.derived_status" />
        </div>
        <!-- Action buttons -->
        <div class="header-actions">
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
          :data="sortedJobs"
          stripe
          @expand-change="handleExpandChange"
        >
          <el-table-column prop="index" label="#" width="60" />
          <el-table-column prop="name" label="Job Name" min-width="200" />
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

          <!-- Expand row: progress, error detail, images -->
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="expand-content">
                <!-- UUID display -->
                <div class="uuid-section">
                  <el-text size="small" type="info">UUID:</el-text>
                  <el-text size="small" class="uuid-text">{{ row.uuid }}</el-text>
                </div>

                <!-- Error detail (FAILED/ERROR jobs) -->
                <div v-if="expandedErrors.has(row.uuid)">
                  <div v-if="errorLoading.has(row.uuid)" class="error-loading">
                    <el-skeleton :rows="3" animated />
                  </div>
                  <div v-else-if="jobErrors.get(row.uuid)?.available" class="error-content">
                    <div class="error-message">
                      <el-text type="danger" tag="div" size="small">
                        {{ jobErrors.get(row.uuid)?.message }}
                      </el-text>
                    </div>
                    <el-collapse class="traceback-collapse">
                      <el-collapse-item title="Traceback">
                        <pre class="traceback-pre">{{ jobErrors.get(row.uuid)?.traceback }}</pre>
                      </el-collapse-item>
                    </el-collapse>
                  </div>
                  <div v-else class="error-unavailable">
                    <el-text type="info">No error information available.</el-text>
                    <el-button type="text" size="small" @click.stop="retryJobError(row)" style="margin-left: 8px;">
                      Retry
                    </el-button>
                  </div>
                </div>

                <!-- Progress (RUNNING / COMPLETED) -->
                <div v-if="jobProgress.get(row.uuid)?.available" class="progress-section">
                  <el-progress
                    v-if="jobProgress.get(row.uuid)?.percent != null"
                    :percentage="Math.min(jobProgress.get(row.uuid)!.percent!, 100)"
                    :stroke-width="18"
                    :text-inside="true"
                  />
                  <el-progress
                    v-else
                    :percentage="100"
                    :indeterminate="true"
                    :stroke-width="18"
                    status="warning"
                  >
                    <span>In progress...</span>
                  </el-progress>
                  <div class="progress-details">
                    <template v-if="jobProgress.get(row.uuid)?.step_type === 'scf' && jobProgress.get(row.uuid)?.batch">
                      <el-text size="small">
                        Completed {{ jobProgress.get(row.uuid)?.current_step || 0 }} / {{ jobProgress.get(row.uuid)?.total_steps }} frames
                      </el-text>
                      <el-text
                        v-if="jobProgress.get(row.uuid)!.batch!.failed > 0"
                        size="small"
                        type="danger"
                        style="margin-left: 12px;"
                      >
                        {{ jobProgress.get(row.uuid)!.batch!.failed }} failed
                      </el-text>
                    </template>
                    <template v-else>
                      <el-text size="small">
                        Step {{ jobProgress.get(row.uuid)?.current_step || 0 }}
                        <template v-if="jobProgress.get(row.uuid)?.total_steps">
                          / {{ jobProgress.get(row.uuid)?.total_steps }}
                        </template>
                      </el-text>
                    </template>
                    <el-text
                      v-if="jobProgress.get(row.uuid)?.last_temp != null && (jobProgress.get(row.uuid)?.step_type === 'nvt' || jobProgress.get(row.uuid)?.step_type === 'nve')"
                      size="small"
                      style="margin-left: 16px;"
                    >
                      Temp: {{ jobProgress.get(row.uuid)?.last_temp?.toFixed(1) }} K
                    </el-text>
                    <el-text
                      v-if="jobProgress.get(row.uuid)?.last_energy != null"
                      size="small"
                      style="margin-left: 16px;"
                    >
                      E: {{ jobProgress.get(row.uuid)?.last_energy?.toFixed(4) }} eV
                    </el-text>
                  </div>
                  <!-- SCF electronic step (RUNNING only) -->
                  <div v-if="row.derived_state === 'RUNNING' && jobProgress.get(row.uuid)?.current_frame" class="scf-estep-detail">
                    <el-text size="small" type="warning">
                      {{ jobProgress.get(row.uuid)!.current_frame!.name }}:
                      electronic step
                      {{ jobProgress.get(row.uuid)!.current_frame!.electronic_step_current ?? '?' }}
                      <template v-if="jobProgress.get(row.uuid)!.current_frame!.electronic_step_limit != null">
                        / {{ jobProgress.get(row.uuid)!.current_frame!.electronic_step_limit }}
                      </template>
                      <template v-if="jobProgress.get(row.uuid)!.current_frame!.scf_algorithm">
                        ({{ jobProgress.get(row.uuid)!.current_frame!.scf_algorithm }})
                      </template>
                    </el-text>
                  </div>
                </div>

                <!-- Input Parameters (INCAR + KPOINTS, lazy loaded) -->
                <div
                  v-if="jobInputParams.get(row.uuid)?.available"
                  class="input-params-section"
                >
                  <el-collapse>
                    <el-collapse-item title="Input Parameters">
                      <!-- INCAR table -->
                      <template v-if="jobInputParams.get(row.uuid)?.incar">
                        <el-text size="small" type="info" tag="div" style="margin-bottom: 6px; font-weight: 600;">INCAR</el-text>
                        <el-descriptions :column="2" border size="small" class="incar-table">
                          <el-descriptions-item
                            v-for="(val, key) in jobInputParams.get(row.uuid)!.incar!"
                            :key="key"
                            :label="String(key)"
                          >
                            {{ val }}
                          </el-descriptions-item>
                        </el-descriptions>
                      </template>

                      <!-- KPOINTS block -->
                      <template v-if="jobInputParams.get(row.uuid)?.kpoints_text">
                        <el-text size="small" type="info" tag="div" style="margin-top: 12px; margin-bottom: 6px; font-weight: 600;">KPOINTS</el-text>
                        <pre class="kpoints-pre">{{ jobInputParams.get(row.uuid)!.kpoints_text }}</pre>
                      </template>

                      <!-- Warning -->
                      <el-text
                        v-if="jobInputParams.get(row.uuid)?.warning"
                        size="small"
                        type="warning"
                        tag="div"
                        style="margin-top: 8px;"
                      >
                        {{ jobInputParams.get(row.uuid)!.warning }}
                      </el-text>
                    </el-collapse-item>
                  </el-collapse>
                </div>

                <!-- MD Timeseries chart (NVT/NVE jobs) -->
                <JobMdTimeseriesPanel
                  v-if="isMdJob(row)"
                  :task-id="taskId"
                  :job-uuid="row.uuid"
                  :step-type="jobProgress.get(row.uuid)?.step_type"
                />

                <!-- Result images (COMPLETED, loaded on expand) -->
                <div
                  v-if="row.derived_state === 'COMPLETED' && jobImages.get(row.uuid)?.images?.length"
                  class="images-section"
                >
                  <el-text size="small" type="info" style="margin-bottom: 8px;">Result Images</el-text>
                  <div class="images-grid">
                    <div
                      v-for="img in jobImages.get(row.uuid)!.images"
                      :key="img.url"
                      v-lazy-image="() => onImageVisible(row.uuid, img)"
                      class="result-image-wrapper"
                    >
                      <el-image
                        v-if="imageBlobUrls.get(img.url)"
                        :src="imageBlobUrls.get(img.url)!"
                        :preview-src-list="jobImages.get(row.uuid)!.images.map(i => imageBlobUrls.get(i.url) || '').filter(u => u)"
                        fit="contain"
                        class="result-image"
                        :alt="img.name"
                      />
                      <el-skeleton v-else :rows="0" animated class="result-image" />
                    </div>
                  </div>
                </div>

                <!-- Output files section -->
                <div
                  v-if="jobFiles.get(row.uuid)?.files?.length"
                  class="files-section"
                >
                  <el-divider content-position="left">Output Files</el-divider>
                  <div class="files-grid">
                    <div
                      v-for="file in jobFiles.get(row.uuid)!.files"
                      :key="file.name"
                      class="file-item"
                      @click="downloadFile(row, file.name)"
                    >
                      <el-icon><Document /></el-icon>
                      <span class="file-name">{{ file.name }}</span>
                      <span class="file-size">{{ formatFileSize(file.size) }}</span>
                    </div>
                  </div>
                </div>
              </div>
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

  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Document } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useTasksStore } from '@/stores/tasks'
import { fetchJobError, stopTask, deleteTask, getJobFiles, getJobFile, getJobProgress, getJobImages, getJobInputParams } from '@/api/tasks'
import StatusBadge from '@/components/StatusBadge.vue'
import JobStepTimeline from '@/components/JobStepTimeline.vue'
import JobMdTimeseriesPanel from '@/components/JobMdTimeseriesPanel.vue'
import type { JobStatusItem, JobErrorResponse, JobFilesResponse, JobProgressResponse, JobImagesResponse, JobInputParamsResponse } from '@/api/types'

const POLL_INTERVAL_MS = 30_000

const route = useRoute()
const router = useRouter()
const tasksStore = useTasksStore()

const task = computed(() => tasksStore.currentTask)
const jobsStatus = computed(() => tasksStore.currentJobsStatus)
const loading = computed(() => tasksStore.loading)


// Error expansion state
const expandedErrors = ref<Set<string>>(new Set())
const jobErrors = ref<Map<string, JobErrorResponse>>(new Map())
const errorLoading = ref<Set<string>>(new Set())

// Job progress, images, and files state
const jobProgress = ref<Map<string, JobProgressResponse>>(new Map())
const jobImages = ref<Map<string, JobImagesResponse>>(new Map())
const jobFiles = ref<Map<string, JobFilesResponse>>(new Map())
const jobInputParams = ref<Map<string, JobInputParamsResponse>>(new Map())
const imageBlobUrls = ref<Map<string, string>>(new Map())

// Operation loading states
const stopping = ref(false)
const deleting = ref(false)

// Polling
let pollTimer: ReturnType<typeof setInterval> | null = null
let isPollingInProgress = false
let isPageVisible = ref(!document.hidden)
let isPageFocused = ref(document.hasFocus())

const taskId = computed(() => route.params.taskId as string)

const truncatedTaskId = computed((): string => {
  const id = taskId.value
  if (id.length <= 20) return id
  return `${id.slice(0, 12)}...${id.slice(-8)}`
})

const sortedJobs = computed((): JobStatusItem[] => {
  if (!jobsStatus.value?.jobs) return []
  return [...jobsStatus.value.jobs].sort((a, b) => a.index - b.index)
})

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

onMounted(async () => {
  try {
    // TaskDetail and TaskJobsStatusResponse are the same type, avoid duplicate requests
    await tasksStore.fetchTaskDetail(taskId.value)
    // Load progress/images/files for existing jobs
    await refreshJobExtras()
  } catch {
    // Error is handled by store
  }
  startPolling()
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('focus', handleFocus)
  window.addEventListener('blur', handleBlur)
})

onUnmounted(() => {
  stopPolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  window.removeEventListener('focus', handleFocus)
  window.removeEventListener('blur', handleBlur)
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

async function loadJobProgress(job: JobStatusItem): Promise<void> {
  try {
    const progress = await getJobProgress(taskId.value, job.uuid)
    jobProgress.value.set(job.uuid, progress)
    jobProgress.value = new Map(jobProgress.value)
  } catch {
    // Silently ignore progress fetch errors
  }
}

async function loadJobImages(job: JobStatusItem): Promise<void> {
  if (jobImages.value.has(job.uuid)) return
  try {
    const images = await getJobImages(taskId.value, job.uuid)
    jobImages.value.set(job.uuid, images)
    jobImages.value = new Map(jobImages.value)
  } catch {
    // Silently ignore
  }
}

/** Load blob URL for a single image on demand. */
async function loadImageBlob(jobUuid: string, img: { url: string; name: string }): Promise<void> {
  if (imageBlobUrls.value.has(img.url)) return
  try {
    const blob = await getJobFile(taskId.value, jobUuid, img.name)
    const blobUrl = URL.createObjectURL(blob)
    imageBlobUrls.value.set(img.url, blobUrl)
    imageBlobUrls.value = new Map(imageBlobUrls.value)
  } catch {
    // Skip
  }
}

/**
 * Trigger lazy loading of a single image blob when its container
 * becomes visible in the viewport.  Called by the IntersectionObserver
 * wired up through ``v-lazy-image``.
 */
function onImageVisible(jobUuid: string, img: { url: string; name: string }): void {
  loadImageBlob(jobUuid, img)
}

// Custom directive: v-lazy-image
// Observes the element; when it enters the viewport the provided callback
// is invoked once, then observation stops.
const vLazyImage = {
  mounted(el: HTMLElement, binding: { value: () => void }) {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            binding.value()
            observer.unobserve(el)
          }
        }
      },
      { rootMargin: '200px' }
    )
    observer.observe(el)
    ;(el as any).__lazyObserver = observer
  },
  unmounted(el: HTMLElement) {
    const observer = (el as any).__lazyObserver as IntersectionObserver | undefined
    if (observer) {
      observer.disconnect()
    }
  },
}

async function loadJobFiles(job: JobStatusItem): Promise<void> {
  if (jobFiles.value.has(job.uuid)) return
  try {
    const files = await getJobFiles(taskId.value, job.uuid)
    jobFiles.value.set(job.uuid, files)
    jobFiles.value = new Map(jobFiles.value)
  } catch {
    // Silently ignore
  }
}

async function loadJobInputParams(job: JobStatusItem): Promise<void> {
  // Allow retry if previously cached as unavailable (run_dir may not have existed yet)
  const cached = jobInputParams.value.get(job.uuid)
  if (cached?.available) return
  try {
    const params = await getJobInputParams(taskId.value, job.uuid)
    jobInputParams.value.set(job.uuid, params)
    jobInputParams.value = new Map(jobInputParams.value)
  } catch {
    // Silently ignore
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

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// Fetch progress only for RUNNING jobs.
// COMPLETED job progress is loaded on-demand when a row is expanded.
async function refreshJobExtras(): Promise<void> {
  if (!jobsStatus.value?.jobs) return
  const promises: Promise<void>[] = []
  for (const job of jobsStatus.value.jobs) {
    if (job.derived_state === 'RUNNING') {
      promises.push(loadJobProgress(job))
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
    const result = await stopTask(taskId.value)
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
    await deleteTask(taskId.value)
    ElMessage.success('Task deleted')
    router.push({ name: 'task-list' })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to delete task'
    ElMessage.error(message)
  } finally {
    deleting.value = false
  }
}

// ============================================
// Auto-polling
// ============================================

function shouldPoll(): boolean {
  return hasRunningJobs.value && isPageVisible.value && isPageFocused.value
}

function startPolling(): void {
  stopPolling()
  if (!shouldPoll()) return
  pollTimer = setInterval(pollJobs, POLL_INTERVAL_MS)
}

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollJobs(): Promise<void> {
  if (!shouldPoll() || isPollingInProgress) {
    if (!shouldPoll()) stopPolling()
    return
  }
  isPollingInProgress = true
  try {
    const result = await tasksStore.fetchJobsStatusSilent(taskId.value)
    // Refresh progress/images/files alongside status polling
    await refreshJobExtras()
    // Check if all jobs are now terminal -- if so, stop polling
    const activeStates = new Set(['RUNNING', 'PENDING'])
    const hasActive = result.jobs.some(
      job => job.derived_state !== null && activeStates.has(job.derived_state)
    )
    if (!hasActive) {
      stopPolling()
    }
  } catch {
    // Silently ignore polling errors
  } finally {
    isPollingInProgress = false
  }
}

function handleVisibilityChange(): void {
  isPageVisible.value = !document.hidden
  if (isPageVisible.value) {
    // Page became visible: restart polling if needed, pollJobs() will be called by startPolling()
    if (shouldPoll()) {
      startPolling()
    }
  } else {
    // Page became hidden
    stopPolling()
  }
}

function handleFocus(): void {
  isPageFocused.value = true
  if (shouldPoll()) {
    startPolling()
  }
}

function handleBlur(): void {
  isPageFocused.value = false
  stopPolling()
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
  router.push({ name: 'task-list' })
}

function isMdJob(job: JobStatusItem): boolean {
  const stepType = jobProgress.value.get(job.uuid)?.step_type
  return stepType === 'nvt' || stepType === 'nve'
}

function handleExpandChange(row: JobStatusItem, expandedRows: JobStatusItem[]): void {
  const isExpanded = expandedRows.some(r => r.uuid === row.uuid)
  if (!isExpanded) return

  // Load files and input params on demand when any job row is expanded
  loadJobFiles(row)
  loadJobInputParams(row)

  // Always reload progress for COMPLETED jobs on expand, so that
  // jobs that transitioned from RUNNING -> COMPLETED show final state
  // instead of stale cached data from the last poll cycle.
  if (row.derived_state === 'COMPLETED') {
    loadJobProgress(row)
  }

  // Load image list on demand when a COMPLETED job row is expanded.
  // Individual image blobs are loaded lazily when they enter the viewport
  // (see the IntersectionObserver setup in the template), not eagerly.
  if (row.derived_state === 'COMPLETED') {
    loadJobImages(row)
  }
}
</script>

<style scoped>
.task-detail-page {
  padding: 24px;
  max-width: 1000px;
  margin: 0 auto;
}

.skeleton-container {
  padding: 24px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 24px;
}

.header-info {
  display: flex;
  align-items: center;
  gap: 12px;
  flex: 1;
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.task-id {
  margin: 0;
  font-size: 18px;
  font-family: monospace;
}

.card-title {
  font-weight: 600;
}

.timeline-card {
  margin-bottom: 24px;
}

.jobs-card {
  margin-bottom: 24px;
}

.no-error {
  color: var(--el-text-color-placeholder);
}

/* Error detail styles */
.job-error-detail {
  padding: 12px 16px;
  margin: 0 16px 8px;
  background-color: var(--el-color-danger-light-9);
  border-radius: 4px;
  border-left: 3px solid var(--el-color-danger);
}

.error-loading {
  padding: 8px 0;
}

.error-message {
  margin-bottom: 8px;
}

.error-content {
  padding: 4px 0;
}

.traceback-collapse {
  border: none;
}

.traceback-pre {
  font-family: 'Courier New', Courier, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  background-color: var(--el-fill-color-light);
  padding: 12px;
  border-radius: 4px;
  margin: 0;
  max-height: 400px;
  overflow-y: auto;
}

.error-unavailable {
  padding: 4px 0;
}

/* Expand row content */
.expand-content {
  padding: 12px 16px;
}

.uuid-section {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.uuid-text {
  font-family: monospace;
  font-size: 12px;
  color: var(--el-text-color-regular);
  user-select: all;
}

.progress-section {
  margin-bottom: 8px;
}

.images-section {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.progress-details {
  margin-top: 6px;
  display: flex;
  align-items: center;
}

.scf-estep-detail {
  margin-top: 4px;
  padding-top: 4px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.images-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 8px 0;
}

.result-image-wrapper {
  width: 280px;
  height: 210px;
}

.result-image {
  width: 280px;
  height: 210px;
  border-radius: 4px;
  border: 1px solid var(--el-border-color-lighter);
}

/* Files section in expand row */
.files-section {
  margin-top: 8px;
}

.files-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.file-item:hover {
  background-color: var(--el-fill-color-light);
}

.file-name {
  font-family: monospace;
  font-size: 13px;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

/* Input parameters section */
.input-params-section {
  margin-bottom: 8px;
}

.incar-table :deep(.el-descriptions__label) {
  font-family: monospace;
  font-size: 12px;
  font-weight: 600;
  min-width: 120px;
}

.incar-table :deep(.el-descriptions__content) {
  font-family: monospace;
  font-size: 12px;
}

.kpoints-pre {
  font-family: 'Courier New', Courier, monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  background-color: var(--el-fill-color-light);
  padding: 10px 12px;
  border-radius: 4px;
  margin: 0;
}
</style>
