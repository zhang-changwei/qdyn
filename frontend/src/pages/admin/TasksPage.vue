<template>
  <div class="tasks-page">
    <h2 class="page-heading">All Tasks</h2>

    <!-- Filters -->
    <el-card class="filter-card" shadow="never">
      <el-form :inline="true" class="filter-form">
        <el-form-item label="Owner">
          <el-input
            v-model="filterOwner"
            placeholder="Filter by owner"
            clearable
            @clear="handleSearch"
            @keyup.enter="handleSearch"
          />
        </el-form-item>
        <el-form-item label="Status">
          <el-select
            v-model="filterStatus"
            placeholder="All statuses"
            clearable
            @change="handleSearch"
          >
            <el-option label="Running" value="RUNNING" />
            <el-option label="Completed" value="COMPLETED" />
            <el-option label="Failed" value="FAILED" />
            <el-option label="Pending" value="PENDING" />
            <el-option label="Paused" value="PAUSED" />
            <el-option label="Stopped" value="STOPPED" />
            <el-option label="Error" value="ERROR" />
            <el-option label="Queued" value="QUEUED" />
            <el-option label="Dispatching" value="DISPATCHING" />
            <el-option label="Cancelled" value="CANCELLED" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="handleSearch">
            Search
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- Loading skeleton -->
    <div v-if="loading && tasks.length === 0" class="skeleton-container">
      <el-skeleton
        v-for="i in 3"
        :key="i"
        :rows="3"
        animated
        class="task-skeleton"
      />
    </div>

    <!-- Task grid -->
    <div v-else-if="tasks.length > 0" class="task-grid">
      <TaskCard
        v-for="task in tasks"
        :key="task.task_id"
        :task="task"
        :admin-mode="true"
        @admin-click="handleAdminClick"
      />
    </div>

    <!-- Empty state -->
    <el-empty v-else description="No tasks found" />

    <!-- Total count -->
    <div v-if="totalTasks > 0" class="total-count">
      Total: {{ totalTasks }} tasks
    </div>

    <!-- Task detail dialog -->
    <el-dialog
      v-model="detailDialogVisible"
      title="Task Details"
      width="700px"
    >
      <template v-if="selectedTask">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="Task ID">
            <code>{{ selectedTask.task_id }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="Owner">
            {{ selectedTask.owner }}
          </el-descriptions-item>
          <el-descriptions-item label="Status">
            <el-tag
              :type="statusTagType(selectedTask.derived_status)"
              size="small"
            >
              {{ selectedTask.derived_status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="Formula">
            {{ selectedTask.formula || '--' }}
          </el-descriptions-item>
          <el-descriptions-item label="Atoms">
            {{ selectedTask.num_atoms ?? '--' }}
          </el-descriptions-item>
          <el-descriptions-item label="Steps">
            {{ selectedTask.steps.join(' > ') || '--' }}
          </el-descriptions-item>
          <el-descriptions-item label="Total Jobs">
            {{ selectedTask.total_jobs }}
          </el-descriptions-item>
          <el-descriptions-item label="Created">
            {{ formatTimestamp(selectedTask.created_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="Worker">
            {{ selectedTask.pool_name || selectedTask.worker || '--' }}
          </el-descriptions-item>
          <el-descriptions-item v-if="selectedTask.prev_task_id" label="Resumed From">
            <code>{{ selectedTask.prev_task_id }}</code>
          </el-descriptions-item>
          <el-descriptions-item label="Work Directory">
            <div v-if="workDirLoading" class="work-dir-loading">
              <el-icon class="is-loading"><Loading /></el-icon>
              Loading...
            </div>
            <code v-else-if="workDir">{{ workDir }}</code>
            <el-text v-else type="info">Not available</el-text>
          </el-descriptions-item>
        </el-descriptions>

        <!-- Jobs list -->
        <div class="jobs-section">
          <h4>Jobs</h4>
          <div v-if="jobsLoading" v-loading="true" style="min-height: 60px" />
          <el-table
            v-else-if="taskJobs.length > 0"
            :data="taskJobs"
            size="small"
            stripe
            class="jobs-table"
          >
            <el-table-column prop="name" label="Name" min-width="120" />
            <el-table-column label="Status" width="130">
              <template #default="{ row }">
                <el-tag
                  :type="jobStatusTagType(row.derived_state || row.state)"
                  size="small"
                >
                  {{ row.derived_state || row.state }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="Created" width="160">
              <template #default="{ row }">
                {{ row.created_on ? new Date(row.created_on).toLocaleString('zh-CN') : '--' }}
              </template>
            </el-table-column>
            <el-table-column prop="error" label="Error" min-width="150" show-overflow-tooltip />
          </el-table>
          <el-text v-else type="info">No jobs found</el-text>
        </div>
      </template>

      <template #footer>
        <div class="dialog-actions">
          <el-button @click="goToTaskDetail">View Full Details</el-button>
          <el-button
            type="warning"
            :loading="actionLoading"
            @click="handleStop"
          >
            Stop
          </el-button>
          <el-button
            type="success"
            :loading="actionLoading"
            @click="handleContinue"
          >
            Continue
          </el-button>
          <el-button
            type="danger"
            :loading="actionLoading"
            @click="deleteConfirmVisible = true"
          >
            Delete
          </el-button>
        </div>
      </template>
    </el-dialog>

    <!-- Delete confirmation dialog -->
    <el-dialog
      v-model="deleteConfirmVisible"
      title="Confirm Delete"
      width="450px"
      :close-on-click-modal="false"
    >
      <p>
        Delete task <code>{{ selectedTask?.task_id }}</code>
        owned by <strong>{{ selectedTask?.owner }}</strong>?
      </p>
      <p>This will stop all running jobs and remove task records.</p>
      <el-checkbox v-model="deleteCleanupDirs" class="cleanup-checkbox">
        Also delete run directories on disk
      </el-checkbox>
      <template #footer>
        <el-button @click="deleteConfirmVisible = false">Cancel</el-button>
        <el-button
          type="danger"
          :loading="actionLoading"
          @click="handleDelete"
        >
          Delete
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { getAdminTasks, getTaskWorkDir, getAdminTaskDetail, adminStopTask, adminContinueTask, adminDeleteTask } from '@/api/admin'
import TaskCard from '@/components/TaskCard.vue'
import type { TaskSummary, DerivedState, JobStatusItem } from '@/api/types'

// Router hooks must be called at the top of <script setup>, before any ref
// that reads route state.
const route = useRoute()
const router = useRouter()

const tasks = ref<TaskSummary[]>([])
const totalTasks = ref(0)
const loading = ref(false)

// Filter state — seed owner from the `?owner=` query param so the first
// fetch (in onMounted) already uses the correct filter.
const filterOwner = ref(
  typeof route.query.owner === 'string' ? route.query.owner : ''
)
const filterStatus = ref('')

// Detail dialog state
const detailDialogVisible = ref(false)
const selectedTask = ref<TaskSummary | null>(null)
const workDir = ref<string | null>(null)
const workDirLoading = ref(false)
const actionLoading = ref(false)
const taskJobs = ref<JobStatusItem[]>([])
const jobsLoading = ref(false)
const deleteConfirmVisible = ref(false)
const deleteCleanupDirs = ref(true)

// Sync owner filter from the `?owner=` query param (e.g. clicking a user in
// UsersPage pushes /admin/tasks?owner=<name>).
//
// Why a watcher instead of a one-shot read inside onMounted:
// 1. useRoute() should be called at the top of <script setup> (Vue Router
//    official guidance) so its reactive route object is available to any
//    downstream ref/watcher, including the initial seed of filterOwner above.
// 2. Vue Router reuses the component instance when only the query changes
//    (e.g. /admin/tasks?owner=A -> /admin/tasks?owner=B without leaving the
//    route). In that case onMounted does NOT re-fire, so a one-shot read in
//    onMounted would keep the stale owner. The watcher fires on every query
//    change and reloads the list with the new filter.
//
// The initial load is handled by onMounted below; the watcher (without
// immediate:true) only handles subsequent query-only navigations.
watch(
  () => route.query.owner,
  (owner) => {
    filterOwner.value = typeof owner === 'string' ? owner : ''
    loadTasks()
  }
)

onMounted(() => {
  loadTasks()
})

// Monotonic request sequence so a late-returning stale request cannot
// overwrite the result of a newer one (e.g. when the user changes filters
// quickly or a query-only navigation races with a manual search).
let loadSeq = 0

async function loadTasks(): Promise<void> {
  const seq = ++loadSeq
  loading.value = true
  try {
    const params: { owner?: string; status?: string } = {}
    if (filterOwner.value) params.owner = filterOwner.value
    if (filterStatus.value) params.status = filterStatus.value
    const response = await getAdminTasks(params)
    // Drop the result if a newer request has been issued in the meantime.
    if (seq !== loadSeq) return
    tasks.value = response.items
    totalTasks.value = response.total
  } catch (err) {
    if (seq !== loadSeq) return
    const message = err instanceof Error ? err.message : 'Failed to load tasks'
    ElMessage.error(message)
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

function handleSearch(): void {
  loadTasks()
}

async function handleAdminClick(task: TaskSummary): Promise<void> {
  selectedTask.value = task
  workDir.value = null
  taskJobs.value = []
  detailDialogVisible.value = true

  // Fetch work directory and job details in parallel
  workDirLoading.value = true
  jobsLoading.value = true

  getTaskWorkDir(task.task_id)
    .then(result => { workDir.value = result.work_dir })
    .catch(() => { workDir.value = null })
    .finally(() => { workDirLoading.value = false })

  getAdminTaskDetail(task.task_id)
    .then(detail => { taskJobs.value = detail.jobs || [] })
    .catch(() => { taskJobs.value = [] })
    .finally(() => { jobsLoading.value = false })
}

function formatTimestamp(ts: number): string {
  return new Date(ts * 1000).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

async function handleStop(): Promise<void> {
  if (!selectedTask.value) return
  actionLoading.value = true
  try {
    const result = await adminStopTask(selectedTask.value.task_id)
    ElMessage.success(`Stopped ${result.stopped.length} jobs`)
    detailDialogVisible.value = false
    await loadTasks()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Failed to stop task')
  } finally {
    actionLoading.value = false
  }
}

async function handleContinue(): Promise<void> {
  if (!selectedTask.value) return
  actionLoading.value = true
  try {
    const result = await adminContinueTask(selectedTask.value.task_id)
    ElMessage.success(`Continued ${result.continued.length} jobs`)
    detailDialogVisible.value = false
    await loadTasks()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Failed to continue task')
  } finally {
    actionLoading.value = false
  }
}

function goToTaskDetail(): void {
  if (!selectedTask.value) return
  detailDialogVisible.value = false
  router.push({ name: 'task-detail', params: { taskId: selectedTask.value.task_id } })
}

async function handleDelete(): Promise<void> {
  if (!selectedTask.value) return
  actionLoading.value = true
  try {
    await adminDeleteTask(selectedTask.value.task_id, deleteCleanupDirs.value)
    ElMessage.success(
      deleteCleanupDirs.value
        ? 'Task deleted (including run directories)'
        : 'Task deleted (directories preserved)'
    )
    deleteConfirmVisible.value = false
    detailDialogVisible.value = false
    await loadTasks()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Failed to delete task')
  } finally {
    actionLoading.value = false
  }
}

function jobStatusTagType(state: string): '' | 'success' | 'warning' | 'danger' | 'info' {
  if (['COMPLETED'].includes(state)) return 'success'
  if (['RUNNING', 'BATCH_RUNNING', 'BATCH_SUBMITTED', 'PAUSED'].includes(state)) return 'warning'
  if (['FAILED', 'REMOTE_ERROR', 'ERROR', 'STOPPED', 'USER_STOPPED'].includes(state)) return 'danger'
  return 'info'
}

function statusTagType(status: DerivedState | null): '' | 'success' | 'warning' | 'danger' | 'info' {
  if (!status) return 'info'
  const map: Record<string, '' | 'success' | 'warning' | 'danger' | 'info'> = {
    RUNNING: 'warning',
    COMPLETED: 'success',
    FAILED: 'danger',
    PENDING: 'info',
    PAUSED: 'warning',
    STOPPED: 'danger',
    ERROR: 'danger',
    QUEUED: 'info',
    DISPATCHING: 'warning',
    CANCELLED: 'info'
  }
  return map[status] ?? 'info'
}
</script>

<style scoped>
.tasks-page {
  max-width: 1200px;
}

.page-heading {
  margin: 0 0 20px;
  font-size: 20px;
  color: var(--el-text-color-primary);
}

.filter-card {
  margin-bottom: 16px;
}

.filter-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.skeleton-container {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-skeleton {
  padding: 16px;
  background-color: var(--el-bg-color);
  border-radius: 8px;
}

.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}

.total-count {
  margin-top: 16px;
  text-align: right;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.work-dir-loading {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--el-text-color-secondary);
}

.failed-detail {
  margin-top: 16px;
}

.failed-detail h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.failed-tag {
  margin-right: 6px;
  margin-bottom: 4px;
}

:deep(.el-descriptions) code {
  word-break: break-all;
  font-size: 12px;
}

:deep(.el-dialog__body) {
  overflow-x: hidden;
}

.jobs-section {
  margin-top: 16px;
}

.jobs-section h4 {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.jobs-table {
  width: 100%;
}

.dialog-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.cleanup-checkbox {
  margin-top: 12px;
}
</style>
