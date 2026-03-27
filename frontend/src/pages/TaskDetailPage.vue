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
              <span v-else class="no-error">-</span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="No jobs found" />
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft } from '@element-plus/icons-vue'
import { useTasksStore } from '@/stores/tasks'
import { getJobStatusDetail } from '@/api/tasks'
import StatusBadge from '@/components/StatusBadge.vue'
import JobStepTimeline from '@/components/JobStepTimeline.vue'
import type { JobStatusItem, JobStatusDetailResponse } from '@/api/types'

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

onMounted(async () => {
  try {
    await Promise.all([
      tasksStore.fetchTaskDetail(taskId.value),
      tasksStore.fetchJobsStatus(taskId.value)
    ])
  } catch {
    // Error is handled by store
  }
})

onUnmounted(() => {
  tasksStore.clearCurrentTask()
})

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

.job-detail-content {
  padding: 8px 0;
}

.dialog-loading {
  padding: 16px 0;
}
</style>
