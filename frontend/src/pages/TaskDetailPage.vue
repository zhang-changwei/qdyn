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
              {{ jobDisplayName(row.name) }}
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

          <!-- Expand row: progress, error detail, images -->
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="expand-content">
                <!-- UUID display -->
                <div class="uuid-section">
                  <el-text size="small" type="info">UUID:</el-text>
                  <el-text size="small" class="uuid-text">{{ row.uuid }}</el-text>
                </div>

                <!-- Time information -->
                <div v-if="row.created_on || row.start_time || row.end_time" class="time-section">
                  <el-descriptions :column="2" size="small" border>
                    <el-descriptions-item label="Created">
                      {{ formatDateTime(row.created_on) }}
                    </el-descriptions-item>
                    <el-descriptions-item label="Started">
                      {{ formatDateTime(row.start_time) }}
                    </el-descriptions-item>
                    <el-descriptions-item label="Ended">
                      {{ formatDateTime(row.end_time) }}
                    </el-descriptions-item>
                    <el-descriptions-item label="Duration">
                      {{ computeDuration(row.start_time, row.end_time) }}
                    </el-descriptions-item>
                  </el-descriptions>
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
                    <el-collapse class="traceback-collapse" :model-value="['traceback']">
                      <el-collapse-item title="Traceback" name="traceback">
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

                <!-- Progress loading skeleton -->
                <div v-if="progressLoading.has(row.uuid)" class="section-skeleton">
                  <el-skeleton :rows="2" animated />
                </div>

                <!-- Progress -->
                <div v-if="!progressLoading.has(row.uuid) && jobProgress.get(row.uuid)?.available" class="progress-section">
                  <el-progress
                    v-if="jobProgress.get(row.uuid)?.percent != null"
                    :percentage="Math.min(jobProgress.get(row.uuid)!.percent!, 100)"
                    :stroke-width="18"
                    :text-inside="true"
                  />
                  <el-progress
                    v-else-if="row.derived_state === 'RUNNING'"
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
                    <template v-else-if="jobProgress.get(row.uuid)?.step_type === 'fused_cat'">
                      <el-text size="small">CA-NAC aggregation</el-text>
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
                  <!-- Failed frames panel (SCF only) -->
                  <div v-if="jobProgress.get(row.uuid)?.failed_frames?.length" class="failed-frames-section">
                    <el-collapse>
                      <el-collapse-item :title="`Failed Frames in ${row.name} (${jobProgress.get(row.uuid)!.failed_frames.length})`">
                        <div class="failed-frames-list">
                          <el-tag
                            v-for="frame in jobProgress.get(row.uuid)!.failed_frames"
                            :key="frame"
                            type="danger"
                            size="small"
                            effect="plain"
                          >
                            {{ frame }}
                          </el-tag>
                        </div>
                      </el-collapse-item>
                    </el-collapse>
                  </div>
                </div>

                <!-- Input Parameters loading skeleton -->
                <div v-if="inputParamsLoading.has(row.uuid)" class="section-skeleton">
                  <el-skeleton :rows="3" animated />
                </div>

                <!-- Input Parameters (lazy loaded) -->
                <div
                  v-if="!inputParamsLoading.has(row.uuid) && jobInputParams.get(row.uuid)?.available"
                  class="input-params-section"
                >
                  <el-collapse>
                    <el-collapse-item title="Input Parameters">
                      <!-- Generic parameters table (PRE_NAMD / NAMD) -->
                      <template v-if="jobInputParams.get(row.uuid)?.parameters">
                        <el-text size="small" type="info" tag="div" style="margin-bottom: 6px; font-weight: 600;">
                          {{ jobInputParams.get(row.uuid)?.parameters_title || 'Parameters' }}
                        </el-text>
                        <el-descriptions :column="2" border size="small" class="incar-table">
                          <el-descriptions-item
                            v-for="(val, key) in jobInputParams.get(row.uuid)!.parameters!"
                            :key="key"
                          >
                            <template #label>
                              <span>{{ key }}</span>
                            </template>
                            {{ val }}
                          </el-descriptions-item>
                        </el-descriptions>
                      </template>

                      <!-- INCAR table -->
                      <template v-if="jobInputParams.get(row.uuid)?.incar">
                        <el-text size="small" type="info" tag="div" style="margin-bottom: 6px; font-weight: 600;">INCAR</el-text>
                        <el-descriptions :column="2" border size="small" class="incar-table">
                          <el-descriptions-item
                            v-for="(val, key) in jobInputParams.get(row.uuid)!.incar!"
                            :key="key"
                          >
                            <template #label>
                              <el-tooltip
                                v-if="INCAR_DESCRIPTIONS[String(key)]"
                                :content="INCAR_DESCRIPTIONS[String(key)]"
                                placement="top"
                                :show-after="300"
                              >
                                <span class="incar-key-with-desc">{{ key }}</span>
                              </el-tooltip>
                              <span v-else>{{ key }}</span>
                            </template>
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

                <!-- MD Timeseries chart (NVT/NVE jobs) — visible once progress data is available -->
                <JobMdTimeseriesPanel
                  v-if="!progressLoading.has(row.uuid) && isMdJob(row)"
                  :task-id="taskId"
                  :job-uuid="row.uuid"
                  :step-type="jobProgress.get(row.uuid)?.step_type"
                />

                <!-- Output files loading skeleton -->
                <div v-if="filesLoading.has(row.uuid)" class="section-skeleton">
                  <el-skeleton :rows="3" animated />
                </div>

                <!-- Output files section (categorized, images first with preview) -->
                <div
                  v-if="!filesLoading.has(row.uuid) && jobFiles.get(row.uuid)?.files?.length"
                  class="files-section"
                >
                  <template
                    v-for="group in groupFilesByCategory(jobFiles.get(row.uuid)!.files)"
                    :key="group.label"
                  >
                    <el-divider content-position="left">{{ group.label }}</el-divider>

                    <!-- Images: inline preview grid with download -->
                    <div v-if="group.category === 'image'" class="images-grid">
                      <div
                        v-for="file in group.files"
                        :key="file.name"
                        class="image-card"
                      >
                        <el-image
                          v-if="imageBlobUrls.get(`${row.uuid}/${file.name}`)"
                          :src="imageBlobUrls.get(`${row.uuid}/${file.name}`)!"
                          :preview-src-list="group.files
                            .map(f => imageBlobUrls.get(`${row.uuid}/${f.name}`) || '')
                            .filter(u => u)"
                          fit="contain"
                          class="result-image"
                          :alt="file.name"
                        />
                        <el-skeleton v-else :rows="0" animated class="result-image" />
                        <div class="image-caption">
                          <span class="image-name" :title="file.name">{{ file.name }}</span>
                          <span class="file-size-text">{{ formatFileSize(file.size) }}</span>
                          <el-button size="small" text type="primary" @click="downloadFile(row, file.name)">
                            <el-icon><Download /></el-icon>
                          </el-button>
                        </div>
                      </div>
                    </div>

                    <!-- Non-image files: table list -->
                    <el-table
                      v-else
                      :data="group.files"
                      size="small"
                      class="files-table"
                      :show-header="false"
                    >
                      <el-table-column prop="name" min-width="200">
                        <template #default="{ row: file }">
                          <div class="file-name-cell">
                            <el-icon><Document /></el-icon>
                            <span class="file-name-text">{{ file.name }}</span>
                          </div>
                        </template>
                      </el-table-column>
                      <el-table-column width="100" align="right">
                        <template #default="{ row: file }">
                          <span class="file-size-text">{{ formatFileSize(file.size) }}</span>
                        </template>
                      </el-table-column>
                      <el-table-column width="120" align="center">
                        <template #default="{ row: file }">
                          <div class="file-action-cell">
                            <el-tooltip
                              v-if="file.size > LARGE_FILE_THRESHOLD"
                              :content="`Large file (${formatFileSize(file.size)})`"
                              placement="top"
                            >
                              <el-icon class="large-file-warning"><WarningFilled /></el-icon>
                            </el-tooltip>
                            <el-button
                              size="small"
                              text
                              type="primary"
                              @click="downloadFile(row, file.name)"
                            >
                              <el-icon><Download /></el-icon>
                              Download
                            </el-button>
                          </div>
                        </template>
                      </el-table-column>
                    </el-table>
                  </template>
                </div>

                <!-- Subdirectory groups (SCF frames, NVT attempts, etc.) -->
                <div
                  v-if="!filesLoading.has(row.uuid) && jobFiles.get(row.uuid)?.subdirs?.length"
                  class="subdirs-section"
                >
                  <template
                    v-for="sdGroup in groupSubdirsByPrefix(jobFiles.get(row.uuid)!.subdirs)"
                    :key="sdGroup.prefix"
                  >
                    <el-divider content-position="left">
                      <el-icon><FolderOpened /></el-icon>
                      {{ sdGroup.label }} ({{ sdGroup.subdirs.length }})
                    </el-divider>

                    <el-collapse class="subdir-collapse" accordion>
                      <el-collapse-item
                        v-for="sd in sdGroup.subdirs"
                        :key="sd.name"
                        :name="sd.name"
                        @click="loadSubdirFiles(row.uuid, sd.name)"
                      >
                        <template #title>
                          <div class="subdir-title">
                            <el-icon><Folder /></el-icon>
                            <span class="subdir-name">{{ sd.name }}</span>
                            <el-tag
                              :type="subdirStatusType(sd.status)"
                              size="small"
                              effect="plain"
                              class="subdir-status-tag"
                            >
                              {{ sd.status }}
                            </el-tag>
                            <span class="subdir-file-count">{{ sd.file_count }} files</span>
                          </div>
                        </template>

                        <!-- Lazy-loaded subdirectory contents -->
                        <div v-if="subdirFilesLoading.has(`${row.uuid}/${sd.name}`)" class="section-skeleton">
                          <el-skeleton :rows="2" animated />
                        </div>
                        <div v-else-if="subdirFiles.get(`${row.uuid}/${sd.name}`)?.files?.length" class="subdir-files-content">
                          <el-table
                            :data="subdirFiles.get(`${row.uuid}/${sd.name}`)!.files"
                            size="small"
                            class="files-table"
                            :show-header="false"
                          >
                            <el-table-column prop="name" min-width="200">
                              <template #default="{ row: file }">
                                <div class="file-name-cell">
                                  <el-icon><Document /></el-icon>
                                  <span class="file-name-text">{{ file.name }}</span>
                                </div>
                              </template>
                            </el-table-column>
                            <el-table-column width="100" align="right">
                              <template #default="{ row: file }">
                                <span class="file-size-text">{{ formatFileSize(file.size) }}</span>
                              </template>
                            </el-table-column>
                            <el-table-column width="120" align="center">
                              <template #default="{ row: file }">
                                <div class="file-action-cell">
                                  <el-tooltip
                                    v-if="file.size > LARGE_FILE_THRESHOLD"
                                    :content="`Large file (${formatFileSize(file.size)})`"
                                    placement="top"
                                  >
                                    <el-icon class="large-file-warning"><WarningFilled /></el-icon>
                                  </el-tooltip>
                                  <el-button
                                    size="small"
                                    text
                                    type="primary"
                                    @click="downloadSubdirFile(row, sd.name, file.name)"
                                  >
                                    <el-icon><Download /></el-icon>
                                    Download
                                  </el-button>
                                </div>
                              </template>
                            </el-table-column>
                          </el-table>
                        </div>
                        <el-empty
                          v-else-if="subdirFiles.has(`${row.uuid}/${sd.name}`) && !subdirFiles.get(`${row.uuid}/${sd.name}`)?.files?.length"
                          description="No files"
                          :image-size="40"
                        />
                      </el-collapse-item>
                    </el-collapse>
                  </template>
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
import { ref, computed, nextTick, onMounted, onUnmounted, watch, type ComponentPublicInstance } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Document, Download, Edit, WarningFilled, FolderOpened, Folder } from '@element-plus/icons-vue'
import { ElMessageBox, ElMessage } from 'element-plus'
import { useTasksStore } from '@/stores/tasks'
import { fetchJobError, stopTask, continueTask, deleteTask, renameTask, getJobFiles, getJobFile, getSubdirFiles, getSubdirFile, getJobProgress, getJobInputParams } from '@/api/tasks'
import { getTaskStructurePreview } from '@/api/structures'
import { getTaskDisplayName } from '@/utils/task-display'
import StatusBadge from '@/components/StatusBadge.vue'
import JobStepTimeline from '@/components/JobStepTimeline.vue'
import JobMdTimeseriesPanel from '@/components/JobMdTimeseriesPanel.vue'
import StructureViewer from '@/components/StructureViewer.vue'
import { INCAR_DESCRIPTIONS } from '@/utils/incar-descriptions'
import type { JobStatusItem, JobFileItem, JobErrorResponse, JobFilesResponse, JobProgressResponse, JobInputParamsResponse, SubdirInfo, SubdirFilesResponse, StructurePreviewPayload } from '@/api/types'

const POLL_INTERVAL_MS = 30_000
const LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  // 50 MB

const route = useRoute()
const router = useRouter()
const tasksStore = useTasksStore()

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

// Phase ordering: nvt < nve < scf/fused < pre_namd < namd
const PHASE_ORDER: Record<string, number> = {
  nvt: 0,
  nve: 1,
  scf: 2,
  fused_scf_prenamd: 2,
  fused_cat: 2,
  pre_namd: 3,
  namd: 4,
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
  document.addEventListener('visibilitychange', handleVisibilityChange)
  window.addEventListener('focus', handleFocus)
  window.addEventListener('blur', handleBlur)
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

function subdirStatusType(status: string): string {
  switch (status) {
    case 'completed': return 'success'
    case 'running': return 'warning'
    case 'failed': return 'danger'
    case 'pending': return 'info'
    default: return 'info'
  }
}

/** Group subdirs by prefix (e.g. "scf_" -> "SCF Frames") for nested collapse */
interface SubdirGroup {
  label: string
  prefix: string
  subdirs: SubdirInfo[]
}

function groupSubdirsByPrefix(subdirs: SubdirInfo[]): SubdirGroup[] {
  const groups = new Map<string, SubdirInfo[]>()
  for (const sd of subdirs) {
    // Extract prefix: everything before the last _ + digits
    const match = sd.name.match(/^(.+?)_\d+$/)
    const prefix = match ? match[1] : sd.name
    if (!groups.has(prefix)) groups.set(prefix, [])
    groups.get(prefix)!.push(sd)
  }
  const LABELS: Record<string, string> = {
    'scf': 'SCF Frames',
    'nvt_attempt': 'NVT Attempts',
  }
  return Array.from(groups.entries()).map(([prefix, sds]) => ({
    label: LABELS[prefix] || `${prefix} Directories`,
    prefix,
    subdirs: sds,
  }))
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

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

interface FileGroup {
  label: string
  category: string
  files: JobFileItem[]
}

const CATEGORY_ORDER: { key: string; label: string }[] = [
  { key: 'image', label: 'Images' },
  { key: 'input', label: 'Input Files' },
  { key: 'output', label: 'Output Files' },
  { key: 'data', label: 'Data Files' },
]

function groupFilesByCategory(files: JobFileItem[]): FileGroup[] {
  const grouped = new Map<string, JobFileItem[]>()
  for (const file of files) {
    const cat = file.category || 'data'
    if (!grouped.has(cat)) grouped.set(cat, [])
    grouped.get(cat)!.push(file)
  }
  // Sort files within each group by name
  for (const list of grouped.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name))
  }
  // Return groups in defined order, skipping empty categories
  return CATEGORY_ORDER
    .filter(c => grouped.has(c.key))
    .map(c => ({ label: c.label, category: c.key, files: grouped.get(c.key)! }))
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
    const result = await continueTask(taskId.value)
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

// ============================================
// Time formatting helpers
// ============================================

function normalizeUtcDateTime(isoStr: string): string {
  const normalized = isoStr.trim().replace(' ', 'T')
  if (/(?:Z|[+-]\d{2}:\d{2}|[+-]\d{4})$/.test(normalized)) {
    return normalized
  }
  return `${normalized}Z`
}

function formatDateTime(isoStr: string | null | undefined): string {
  if (!isoStr) return '-'
  try {
    const d = new Date(normalizeUtcDateTime(isoStr))
    if (isNaN(d.getTime())) return isoStr
    const pad = (n: number) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  } catch {
    return isoStr
  }
}

function computeDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return '-'
  try {
    const startMs = new Date(normalizeUtcDateTime(start)).getTime()
    const endMs = new Date(normalizeUtcDateTime(end)).getTime()
    if (isNaN(startMs) || isNaN(endMs)) return '-'
    const diffSec = Math.floor((endMs - startMs) / 1000)
    if (diffSec < 0) return '-'
    const hours = Math.floor(diffSec / 3600)
    const minutes = Math.floor((diffSec % 3600) / 60)
    const seconds = diffSec % 60
    if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`
    if (minutes > 0) return `${minutes}m ${seconds}s`
    return `${seconds}s`
  } catch {
    return '-'
  }
}

function isMdJob(job: JobStatusItem): boolean {
  const stepType = jobProgress.value.get(job.uuid)?.step_type
  return stepType === 'nvt' || stepType === 'nve'
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

.task-name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.task-id {
  margin: 0;
  font-size: 18px;
  font-family: monospace;
  cursor: pointer;
}

.task-id:hover {
  color: var(--el-color-primary);
}

.edit-name-icon {
  cursor: pointer;
  color: var(--el-text-color-secondary);
  font-size: 14px;
}

.edit-name-icon:hover {
  color: var(--el-color-primary);
}

.name-edit-input {
  width: 300px;
}

.card-title {
  font-weight: 600;
}

.structure-card {
  margin-bottom: 24px;
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

.time-section {
  margin-bottom: 10px;
}

.resume-tag {
  margin-left: 8px;
}

.resume-link {
  color: var(--el-color-primary);
  text-decoration: none;
  margin-left: 4px;
  font-family: monospace;
  font-size: 12px;
}

.resume-link:hover {
  text-decoration: underline;
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

.failed-frames-section {
  margin-top: 8px;
}

.failed-frames-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-height: 200px;
  overflow-y: auto;
}

.images-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding: 8px 0;
}

.image-card {
  display: flex;
  flex-direction: column;
  width: 300px;
}

.result-image {
  width: 300px;
  height: 220px;
  border-radius: 4px;
  border: 1px solid var(--el-border-color-lighter);
}

.image-caption {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
}

.image-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-regular);
}

/* Files section in expand row */
.files-section {
  margin-top: 8px;
}

.files-table {
  margin-bottom: 4px;
}

.files-table :deep(.el-table__body-wrapper) {
  /* Compact rows inside nested file table */
}

.file-name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.file-name-text {
  font-family: monospace;
  font-size: 13px;
  word-break: break-all;
}

.file-size-text {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  white-space: nowrap;
}

.file-action-cell {
  display: flex;
  align-items: center;
  gap: 4px;
  justify-content: flex-end;
}

.large-file-warning {
  color: var(--el-color-warning);
  font-size: 16px;
}

/* Input parameters section */
/* Skeleton placeholder for lazy-loaded sections within an expanded row */
.section-skeleton {
  margin: 8px 0;
  padding: 8px 0;
}

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

.incar-key-with-desc {
  border-bottom: 1px dashed var(--el-text-color-secondary);
  cursor: help;
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

/* Subdirectory section styles */
.subdirs-section {
  margin-top: 8px;
}

.subdir-collapse {
  border: none;
}

.subdir-collapse :deep(.el-collapse-item__header) {
  height: 36px;
  line-height: 36px;
  font-size: 13px;
  background-color: transparent;
}

.subdir-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}

.subdir-title {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
}

.subdir-name {
  font-family: monospace;
  font-size: 13px;
  font-weight: 500;
}

.subdir-status-tag {
  font-size: 11px;
}

.subdir-file-count {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-left: auto;
  margin-right: 8px;
}

.subdir-files-content {
  padding: 0 8px 8px;
}
</style>
