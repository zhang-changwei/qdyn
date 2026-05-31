<template>
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
    <div v-if="rowState.expandedError">
      <div v-if="rowState.errorLoading" class="error-loading">
        <el-skeleton :rows="3" animated />
      </div>
      <div v-else-if="rowState.error?.available" class="error-content">
        <div class="error-message">
          <el-text type="danger" tag="div" size="small">
            {{ rowState.error?.message }}
          </el-text>
        </div>
        <el-collapse class="traceback-collapse" :model-value="['traceback']">
          <el-collapse-item title="Traceback" name="traceback">
            <pre class="traceback-pre">{{ rowState.error?.traceback }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>
      <div v-else class="error-unavailable">
        <el-text type="info">No error information available.</el-text>
        <el-button type="text" size="small" @click.stop="$emit('retry-error', row)" style="margin-left: 8px;">
          Retry
        </el-button>
      </div>
    </div>

    <!-- Progress loading skeleton -->
    <div v-if="rowState.progressLoading" class="section-skeleton">
      <el-skeleton :rows="2" animated />
    </div>

    <!-- Progress -->
    <div v-if="!rowState.progressLoading && rowState.progress?.available" class="progress-section">
      <el-progress
        v-if="rowState.progress?.percent != null"
        :percentage="Math.min(rowState.progress!.percent!, 100)"
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
        <template v-if="rowState.progress?.step_type === 'scf' && rowState.progress?.batch">
          <el-text size="small">
            Completed {{ rowState.progress?.current_step || 0 }} / {{ rowState.progress?.total_steps }} frames
          </el-text>
          <el-text
            v-if="rowState.progress!.batch!.failed > 0"
            size="small"
            type="danger"
            style="margin-left: 12px;"
          >
            {{ rowState.progress!.batch!.failed }} failed
          </el-text>
        </template>
        <template v-else-if="rowState.progress?.step_type === 'fused_cat'">
          <el-text size="small">CA-NAC aggregation</el-text>
        </template>
        <template v-else>
          <el-text size="small">
            Step {{ rowState.progress?.current_step || 0 }}
            <template v-if="rowState.progress?.total_steps">
              / {{ rowState.progress?.total_steps }}
            </template>
          </el-text>
        </template>
        <el-text
          v-if="rowState.progress?.last_temp != null && (rowState.progress?.step_type === 'nvt' || rowState.progress?.step_type === 'nve')"
          size="small"
          style="margin-left: 16px;"
        >
          Temp: {{ rowState.progress?.last_temp?.toFixed(1) }} K
        </el-text>
        <el-text
          v-if="rowState.progress?.last_energy != null"
          size="small"
          style="margin-left: 16px;"
        >
          E: {{ rowState.progress?.last_energy?.toFixed(4) }} eV
        </el-text>
      </div>
      <!-- SCF electronic step (RUNNING only) -->
      <div v-if="row.derived_state === 'RUNNING' && rowState.progress?.current_frame" class="scf-estep-detail">
        <el-text size="small" type="warning">
          {{ rowState.progress!.current_frame!.name }}:
          electronic step
          {{ rowState.progress!.current_frame!.electronic_step_current ?? '?' }}
          <template v-if="rowState.progress!.current_frame!.electronic_step_limit != null">
            / {{ rowState.progress!.current_frame!.electronic_step_limit }}
          </template>
          <template v-if="rowState.progress!.current_frame!.scf_algorithm">
            ({{ rowState.progress!.current_frame!.scf_algorithm }})
          </template>
        </el-text>
      </div>
      <!-- Failed frames panel (SCF only) -->
      <div v-if="rowState.progress?.failed_frames?.length" class="failed-frames-section">
        <el-collapse>
          <el-collapse-item :title="`Failed Frames in ${row.name} (${rowState.progress!.failed_frames.length})`">
            <div class="failed-frames-list">
              <el-tag
                v-for="frame in rowState.progress!.failed_frames"
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
    <div v-if="rowState.inputParamsLoading" class="section-skeleton">
      <el-skeleton :rows="3" animated />
    </div>

    <!-- Input Parameters (lazy loaded) -->
    <div
      v-if="!rowState.inputParamsLoading && rowState.inputParams?.available"
      class="input-params-section"
    >
      <el-collapse>
        <el-collapse-item title="Input Parameters">
          <!-- Generic parameters table (PRE_NAMD / NAMD) -->
          <template v-if="rowState.inputParams?.parameters">
            <el-text size="small" type="info" tag="div" style="margin-bottom: 6px; font-weight: 600;">
              {{ rowState.inputParams?.parameters_title || 'Parameters' }}
            </el-text>
            <el-descriptions :column="2" border size="small" class="incar-table">
              <el-descriptions-item
                v-for="(val, key) in rowState.inputParams!.parameters!"
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
          <template v-if="rowState.inputParams?.incar">
            <el-text size="small" type="info" tag="div" style="margin-bottom: 6px; font-weight: 600;">INCAR</el-text>
            <el-descriptions :column="2" border size="small" class="incar-table">
              <el-descriptions-item
                v-for="(val, key) in rowState.inputParams!.incar!"
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
          <template v-if="rowState.inputParams?.kpoints_text">
            <el-text size="small" type="info" tag="div" style="margin-top: 12px; margin-bottom: 6px; font-weight: 600;">KPOINTS</el-text>
            <pre class="kpoints-pre">{{ rowState.inputParams!.kpoints_text }}</pre>
          </template>

          <!-- Warning -->
          <el-text
            v-if="rowState.inputParams?.warning"
            size="small"
            type="warning"
            tag="div"
            style="margin-top: 8px;"
          >
            {{ rowState.inputParams!.warning }}
          </el-text>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- MD Timeseries chart (NVT/NVE jobs) — visible once progress data is available -->
    <JobMdTimeseriesPanel
      v-if="!rowState.progressLoading && isMdJob"
      :task-id="taskId"
      :job-uuid="row.uuid"
      :step-type="rowState.progress?.step_type"
    />

    <!-- Output files loading skeleton -->
    <div v-if="rowState.filesLoading" class="section-skeleton">
      <el-skeleton :rows="3" animated />
    </div>

    <!-- Output files section (categorized, images first with preview) -->
    <div
      v-if="!rowState.filesLoading && rowState.files?.files?.length"
      class="files-section"
    >
      <template
        v-for="group in groupFilesByCategory(rowState.files!.files)"
        :key="group.label"
      >
        <el-divider content-position="left">
          {{ group.label }}
          <el-checkbox
            v-if="group.category !== 'image'"
            size="small"
            class="group-select-checkbox"
            :model-value="isGroupAllSelected(row.uuid, group.files)"
            @update:model-value="$emit('toggle-group-selection', row.uuid, group.files)"
            @click.stop
          />
        </el-divider>

        <!-- Images: inline preview grid with download -->
        <div v-if="group.category === 'image'" class="images-grid">
          <div
            v-for="file in group.files"
            :key="file.name"
            class="image-card"
          >
            <el-checkbox
              class="image-select-checkbox"
              :model-value="isFileSelected(row.uuid, file.name)"
              @update:model-value="$emit('toggle-file-selection', row.uuid, file.name)"
              @click.stop
            />
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
              <el-button size="small" text type="primary" @click="$emit('download-file', row, file.name)">
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
          <el-table-column width="40" align="center">
            <template #default="{ row: file }">
              <el-checkbox
                :model-value="isFileSelected(row.uuid, file.name)"
                @update:model-value="$emit('toggle-file-selection', row.uuid, file.name)"
              />
            </template>
          </el-table-column>
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
                  @click="$emit('download-file', row, file.name)"
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
      v-if="!rowState.filesLoading && rowState.files?.subdirs?.length"
      class="subdirs-section"
    >
      <template
        v-for="sdGroup in groupSubdirsByPrefix(rowState.files!.subdirs)"
        :key="sdGroup.prefix"
      >
        <el-divider content-position="left">
          <el-icon><FolderOpened /></el-icon>
          {{ sdGroup.label }} ({{ sdGroup.subdirs.length }})
          <el-checkbox
            size="small"
            class="group-select-checkbox"
            :model-value="isSdGroupAllSelected(row.uuid, sdGroup.subdirs)"
            @update:model-value="$emit('toggle-sd-group-select-all', row.uuid, sdGroup.subdirs)"
            @click.stop
          />
        </el-divider>

        <el-collapse class="subdir-collapse" accordion>
          <el-collapse-item
            v-for="sd in sdGroup.subdirs"
            :key="sd.name"
            :name="sd.name"
            @click="$emit('load-subdir-files', row.uuid, sd.name)"
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
                <el-checkbox
                  size="small"
                  class="subdir-select-checkbox"
                  :model-value="isGroupAllSelected(row.uuid, subdirFiles.get(`${row.uuid}/${sd.name}`)?.files ?? [], sd.name)"
                  @update:model-value="$emit('toggle-subdir-select-all', row.uuid, sd.name)"
                  @click.stop
                />
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
                <el-table-column width="40" align="center">
                  <template #default="{ row: file }">
                    <el-checkbox
                      :model-value="isFileSelected(row.uuid, file.name, sd.name)"
                      @update:model-value="$emit('toggle-file-selection', row.uuid, file.name, sd.name)"
                    />
                  </template>
                </el-table-column>
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
                        @click="$emit('download-subdir-file', row, sd.name, file.name)"
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

<script setup lang="ts">
import { computed } from 'vue'
import { Document, Download, WarningFilled, FolderOpened, Folder } from '@element-plus/icons-vue'
import JobMdTimeseriesPanel from '@/components/JobMdTimeseriesPanel.vue'
import { INCAR_DESCRIPTIONS } from '@/utils/incar-descriptions'
import { formatFileSize, formatDateTime, computeDuration } from '@/utils/format'
import type { JobStatusItem, JobFileItem, JobErrorResponse, JobFilesResponse, JobProgressResponse, JobInputParamsResponse, SubdirInfo, SubdirFilesResponse } from '@/api/types'

const LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  // 50 MB

interface JobExpandedRowState {
  expandedError: boolean
  errorLoading: boolean
  error?: JobErrorResponse
  progressLoading: boolean
  progress?: JobProgressResponse
  inputParamsLoading: boolean
  inputParams?: JobInputParamsResponse
  filesLoading: boolean
  files?: JobFilesResponse
}

const props = defineProps<{
  row: JobStatusItem
  taskId: string
  rowState: JobExpandedRowState
  imageBlobUrls: ReadonlyMap<string, string>
  subdirFiles: ReadonlyMap<string, SubdirFilesResponse>
  subdirFilesLoading: ReadonlySet<string>
  isFileSelected: (jobUuid: string, filename: string, subdir?: string) => boolean
  isGroupAllSelected: (jobUuid: string, files: { name: string }[], subdir?: string) => boolean
  isSdGroupAllSelected: (jobUuid: string, subdirs: { name: string }[]) => boolean
}>()

defineEmits<{
  'retry-error': [row: JobStatusItem]
  'download-file': [row: JobStatusItem, filename: string]
  'load-subdir-files': [jobUuid: string, subdirName: string]
  'download-subdir-file': [row: JobStatusItem, subdir: string, filename: string]
  'toggle-file-selection': [jobUuid: string, filename: string, subdir?: string]
  'toggle-group-selection': [jobUuid: string, files: { name: string }[], subdir?: string]
  'toggle-subdir-select-all': [jobUuid: string, subdirName: string]
  'toggle-sd-group-select-all': [jobUuid: string, subdirs: { name: string }[]]
}>()

// --- Display logic (moved from TaskDetailPage) ---

const isMdJob = computed(() => {
  const stepType = props.rowState.progress?.step_type
  return stepType === 'nvt' || stepType === 'nve'
})


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
  for (const list of grouped.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name))
  }
  return CATEGORY_ORDER
    .filter(c => grouped.has(c.key))
    .map(c => ({ label: c.label, category: c.key, files: grouped.get(c.key)! }))
}

interface SubdirGroup {
  label: string
  prefix: string
  subdirs: SubdirInfo[]
}

function groupSubdirsByPrefix(subdirs: SubdirInfo[]): SubdirGroup[] {
  const groups = new Map<string, SubdirInfo[]>()
  for (const sd of subdirs) {
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

function subdirStatusType(status: string): string {
  switch (status) {
    case 'completed': return 'success'
    case 'running': return 'warning'
    case 'failed': return 'danger'
    case 'pending': return 'info'
    default: return 'info'
  }
}
</script>

<style scoped>
/* Expand row content */
.expand-content {
  padding: var(--space-3) var(--space-4);
}

.uuid-section {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  margin-bottom: var(--space-2);
}

.uuid-text {
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  color: var(--fg-secondary);
  user-select: all;
}

.time-section {
  margin-bottom: 10px;
}

/* Time descriptions within expand rows */
.time-section :deep(.el-descriptions__content),
.time-section :deep(.el-descriptions__label) {
  font-size: var(--fs-12);
  color: var(--fg-tertiary);
}

.error-loading {
  padding: var(--space-2) 0;
}

.error-message {
  margin-bottom: var(--space-2);
}

.error-content {
  padding: var(--space-1) 0;
}

.traceback-collapse {
  border: none;
}

.traceback-pre {
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-all;
  background-color: var(--el-fill-color-light);
  padding: var(--space-3);
  border-radius: var(--radius-sm);
  margin: 0;
  max-height: 400px;
  overflow-y: auto;
}

.error-unavailable {
  padding: var(--space-1) 0;
}

.progress-section {
  margin-bottom: var(--space-2);
}

/* Phosphor color override for RUNNING job progress bars */
.progress-section :deep(.el-progress-bar__inner) {
  background-color: var(--phosphor);
}

.progress-details {
  margin-top: 6px;
  display: flex;
  align-items: center;
}

.scf-estep-detail {
  margin-top: var(--space-1);
  padding-top: var(--space-1);
  border-top: 1px dashed var(--border-subtle);
}

.failed-frames-section {
  margin-top: var(--space-2);
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
  gap: var(--space-4);
  padding: var(--space-2) 0;
}

.image-card {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 300px;
}

.image-select-checkbox {
  position: absolute;
  top: 4px;
  left: 4px;
  z-index: 1;
  padding: 2px 4px;
  background: var(--el-bg-color-overlay);
  border-radius: var(--radius-sm);
}

.result-image {
  width: 300px;
  height: 220px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-subtle);
}

.image-caption {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-1) 0;
  font-size: var(--fs-12);
}

.image-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono);
  color: var(--fg-secondary);
}

/* Files section in expand row */
.files-section {
  margin-top: var(--space-2);
}

.group-select-checkbox {
  margin-left: var(--space-2);
  vertical-align: middle;
}

.files-table {
  margin-bottom: var(--space-1);
}

.file-name-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.file-name-text {
  font-family: var(--font-mono);
  font-size: var(--fs-13);
  word-break: break-all;
}

.file-size-text {
  font-size: var(--fs-12);
  color: var(--fg-tertiary);
  white-space: nowrap;
}

.file-action-cell {
  display: flex;
  align-items: center;
  gap: var(--space-1);
  justify-content: flex-end;
}

.large-file-warning {
  color: var(--warning-fg);
  font-size: var(--fs-16);
}

/* Skeleton placeholder for lazy-loaded sections */
.section-skeleton {
  margin: var(--space-2) 0;
  padding: var(--space-2) 0;
}

.input-params-section {
  margin-bottom: var(--space-2);
}

.incar-table :deep(.el-descriptions__label) {
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  font-weight: 600;
  min-width: 120px;
}

.incar-table :deep(.el-descriptions__content) {
  font-family: var(--font-mono);
  font-size: var(--fs-12);
}

.incar-key-with-desc {
  border-bottom: 1px dashed var(--fg-tertiary);
  cursor: help;
}

.kpoints-pre {
  font-family: var(--font-mono);
  font-size: var(--fs-12);
  line-height: 1.5;
  white-space: pre-wrap;
  background-color: var(--el-fill-color-light);
  padding: 10px 12px;
  border-radius: var(--radius-sm);
  margin: 0;
}

/* Subdirectory section styles */
.subdirs-section {
  margin-top: var(--space-2);
}

.subdir-collapse {
  border: none;
}

.subdir-collapse :deep(.el-collapse-item__header) {
  height: 36px;
  line-height: 36px;
  font-size: var(--fs-13);
  background-color: transparent;
}

.subdir-collapse :deep(.el-collapse-item__wrap) {
  border-bottom: none;
}

.subdir-title {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
}

.subdir-name {
  font-family: var(--font-mono);
  font-size: var(--fs-13);
  font-weight: 500;
}

.subdir-status-tag {
  font-size: 11px;
}

.subdir-file-count {
  font-size: var(--fs-12);
  color: var(--fg-tertiary);
  margin-left: auto;
  margin-right: var(--space-2);
}

.subdir-select-checkbox {
  margin-right: var(--space-2);
}

.subdir-files-content {
  padding: 0 var(--space-2) var(--space-2);
}
</style>
