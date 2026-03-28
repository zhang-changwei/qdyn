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
          @row-click="showJobDetail"
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
              <!-- View error button for FAILED jobs -->
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
        </el-table>

        <!-- Expanded error details -->
        <div
          v-for="job in sortedJobs"
          :key="'error-' + job.uuid"
        >
          <el-collapse-transition>
            <div
              v-if="expandedErrors.has(job.uuid)"
              class="job-error-detail"
            >
              <div v-if="errorLoading.has(job.uuid)" class="error-loading">
                <el-skeleton :rows="3" animated />
              </div>
              <div v-else-if="jobErrors.get(job.uuid)?.available" class="error-content">
                <div class="error-message">
                  <el-text type="danger" tag="div" size="small">
                    {{ jobErrors.get(job.uuid)?.message }}
                  </el-text>
                </div>
                <el-collapse class="traceback-collapse">
                  <el-collapse-item title="Traceback">
                    <pre class="traceback-pre">{{ jobErrors.get(job.uuid)?.traceback }}</pre>
                  </el-collapse-item>
                </el-collapse>
              </div>
              <div v-else class="error-unavailable">
                <el-text type="info">No error information available.</el-text>
                <el-button
                  type="text"
                  size="small"
                  @click="retryJobError(job)"
                  style="margin-left: 8px;"
                >
                  Retry
                </el-button>
              </div>
            </div>
          </el-collapse-transition>
        </div>

        <el-empty v-if="!jobsStatus || jobsStatus.jobs.length === 0" description="No jobs found" />
      </el-card>
    </div>

    <!-- Error state -->
    <el-empty v-else description="Task not found">
      <el-button type="primary" @click="goBack">Go Back</el-button>
    </el-empty>

    <!-- Job detail dialog -->
    <el-dialog
      v-model="jobDetailVisible"
      :title="selectedJob?.name || 'Job Detail'"
      width="600px"
    >
      <div v-if="jobDetailLoading" class="dialog-loading">
        <el-skeleton :rows="4" animated />
      </div>
      <div v-else-if="selectedJobDetail" class="job-detail-content">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="UUID">
            {{ selectedJobDetail.uuid }}
          </el-descriptions-item>
          <el-descriptions-item label="Name">
            {{ selectedJobDetail.name }}
          </el-descriptions-item>
          <el-descriptions-item label="Raw State">
            <el-tag>{{ selectedJobDetail.state }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Status">
            <StatusBadge :status="selectedJobDetail.derived_state" />
          </el-descriptions-item>
          <el-descriptions-item v-if="selectedJobDetail.error" label="Error">
            <el-text type="danger">{{ selectedJobDetail.error }}</el-text>
          </el-descriptions-item>
          <el-descriptions-item v-if="selectedJobDetail.log_note" label="Note">
            <el-text type="info">{{ selectedJobDetail.log_note }}</el-text>
          </el-descriptions-item>
        </el-descriptions>
      </div>
      <el-empty v-else description="Failed to load job detail" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useTasksStore } from '@/stores/tasks'
import { getJobStatusDetail, fetchJobError, stopTask, deleteTask } from '@/api/tasks'
import StatusBadge from '@/components/StatusBadge.vue'
import JobStepTimeline from '@/components/JobStepTimeline.vue'
import type { JobStatusItem, JobStatusDetailResponse, JobErrorResponse } from '@/api/types'

const POLL_INTERVAL_MS = 30_000

const route = useRoute()
const router = useRouter()
const tasksStore = useTasksStore()

const task = computed(() => tasksStore.currentTask)
const jobsStatus = computed(() => tasksStore.currentJobsStatus)
const loading = computed(() => tasksStore.loading)

const jobDetailVisible = ref(false)
const jobDetailLoading = ref(false)
const selectedJob = ref<JobStatusItem | null>(null)
const selectedJobDetail = ref<JobStatusDetailResponse | null>(null)

// Error expansion state
const expandedErrors = ref<Set<string>>(new Set())
const jobErrors = ref<Map<string, JobErrorResponse>>(new Map())
const errorLoading = ref<Set<string>>(new Set())

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
// Navigation and job detail dialog
// ============================================

function goBack(): void {
  router.push({ name: 'task-list' })
}

async function showJobDetail(job: JobStatusItem): Promise<void> {
  selectedJob.value = job
  jobDetailVisible.value = true
  jobDetailLoading.value = true
  selectedJobDetail.value = null

  try {
    const detail = await getJobStatusDetail(taskId.value, job.uuid)
    selectedJobDetail.value = detail
  } catch {
    // Keep dialog open to show error state
  } finally {
    jobDetailLoading.value = false
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

:deep(.el-table__row) {
  cursor: pointer;
}

:deep(.el-table__row:hover) {
  background-color: var(--el-fill-color-light);
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

.job-detail-content {
  padding: 8px 0;
}

.dialog-loading {
  padding: 16px 0;
}
</style>
