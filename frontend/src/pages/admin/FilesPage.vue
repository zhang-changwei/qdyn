<template>
  <div class="files-page">
    <h2 class="page-heading">File Browser</h2>

    <!-- File type statistics bar -->
    <el-card v-if="fileTypeStats.length > 0" shadow="never" class="stats-card">
      <div class="stats-header">
        <span class="stats-title">File Type Statistics</span>
        <el-text type="info" size="small">
          Click a tag to filter by filename
        </el-text>
      </div>
      <div class="stats-tags">
        <el-tag
          v-for="stat in fileTypeStats"
          :key="stat.name"
          class="stat-tag"
          :type="fileNameSearch === stat.name ? 'primary' : 'info'"
          :effect="fileNameSearch === stat.name ? 'dark' : 'plain'"
          size="large"
          @click="handleStatTagClick(stat.name)"
        >
          {{ stat.name }}: {{ formatBytes(stat.totalSize) }}
          ({{ stat.count }} {{ stat.count === 1 ? 'file' : 'files' }})
        </el-tag>
      </div>
    </el-card>

    <!-- Summary bar -->
    <el-card shadow="never" class="summary-card">
      <div class="summary-row">
        <el-text>Base: <code>{{ filesData?.work_dir_base || '--' }}</code></el-text>
        <el-tag>{{ filesData?.total_entries ?? 0 }} job dirs</el-tag>
        <el-tag type="success">{{ uniqueTaskCount }} tasks</el-tag>
        <el-tag v-if="(filesData?.orphan_count ?? 0) > 0" type="warning">
          {{ filesData?.orphan_count }} orphan
        </el-tag>
        <div class="summary-spacer" />
        <el-button
          :icon="RefreshRight"
          :loading="loading"
          @click="loadFiles(true)"
        >
          Refresh
        </el-button>
      </div>
      <div class="summary-row" style="margin-top: 8px">
        <el-radio-group v-model="filterMode" size="small">
          <el-radio-button value="all">All</el-radio-button>
          <el-radio-button value="orphan">Orphan Only</el-radio-button>
          <el-radio-button value="mapped">Mapped Only</el-radio-button>
        </el-radio-group>
        <el-input
          v-model="searchText"
          placeholder="Filter by owner, task ID, or path"
          clearable
          style="width: 260px"
        />
        <el-input
          v-model="fileNameSearch"
          placeholder="Filter by filename (e.g. WAVECAR)"
          clearable
          style="width: 260px"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </div>

      <!-- File name search results summary -->
      <div v-if="fileNameSearch" class="search-summary">
        <el-alert type="info" :closable="false" show-icon>
          <template #title>
            Found <strong>{{ fileNameMatchCount }}</strong> matching files
            in <strong>{{ fileNameMatchDirCount }}</strong> directories
            ({{ formatBytes(fileNameMatchTotalSize) }} total)
          </template>
          <template v-if="fileNameMatchDirCount > 0" #default>
            <el-button
              type="danger"
              size="small"
              plain
              @click="confirmDeleteByName"
            >
              Delete all "{{ fileNameSearch }}" files
            </el-button>
          </template>
        </el-alert>
      </div>

      <!-- Selection bar -->
      <div v-if="selectedEntries.length > 0" class="selection-bar">
        <el-text>
          Selected <strong>{{ selectedEntries.length }}</strong> directories,
          total <strong>{{ formatBytes(selectedTotalSize) }}</strong>
        </el-text>
        <el-button
          type="danger"
          size="small"
          @click="confirmBulkDelete"
        >
          Delete Selected
        </el-button>
      </div>
    </el-card>

    <!-- Directory table -->
    <el-table
      ref="tableRef"
      v-loading="loading"
      :data="filteredEntries"
      stripe
      size="small"
      class="files-table"
      row-key="abs_path"
      :default-sort="{ prop: 'path', order: 'ascending' }"
      @selection-change="handleSelectionChange"
    >
      <el-table-column type="selection" width="40" />
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="expand-content">
            <!-- Top-level files -->
            <div v-if="getGroupedFiles(row).root.length > 0" class="file-group">
              <div class="file-group-files">
                <div
                  v-for="file in getGroupedFiles(row).root"
                  :key="file.name"
                  class="file-row"
                >
                  <span class="file-entry">
                    <el-icon class="file-icon" :class="fileIconClass(file.name)"><Document /></el-icon>
                    <span :class="{ 'highlight-match': isFileNameMatch(file.name) }">{{ file.name }}</span>
                  </span>
                  <span class="file-size">{{ formatBytes(file.size) }}</span>
                  <el-popconfirm title="Delete this file?" @confirm="handleDeleteSingleFile(row, file)">
                    <template #reference>
                      <el-button type="danger" size="small" :icon="Delete" link />
                    </template>
                  </el-popconfirm>
                </div>
              </div>
            </div>
            <!-- Subdirectory groups (collapsible) -->
            <el-collapse v-if="Object.keys(getGroupedFiles(row).subdirs).length > 0" class="subdir-collapse">
              <el-collapse-item
                v-for="(files, subdir) in getGroupedFiles(row).subdirs"
                :key="subdir"
                :name="subdir"
              >
                <template #title>
                  <span class="subdir-title">
                    <el-icon><FolderOpened /></el-icon>
                    {{ subdir }}
                    <el-tag size="small" type="info">{{ files.length }} files</el-tag>
                    <el-tag size="small">{{ formatBytes(files.reduce((s: number, f: FileSummaryItem) => s + f.size, 0)) }}</el-tag>
                  </span>
                </template>
                <div class="file-group-files">
                  <div
                    v-for="file in files"
                    :key="file.name"
                    class="file-row"
                  >
                    <span class="file-entry">
                      <el-icon class="file-icon" :class="fileIconClass(file.name)"><Document /></el-icon>
                      <span :class="{ 'highlight-match': isFileNameMatch(file.name) }">{{ basename(file.name) }}</span>
                    </span>
                    <span class="file-size">{{ formatBytes(file.size) }}</span>
                    <el-popconfirm title="Delete this file?" @confirm="handleDeleteSingleFile(row, file)">
                      <template #reference>
                        <el-button type="danger" size="small" :icon="Delete" link />
                      </template>
                    </el-popconfirm>
                  </div>
                </div>
              </el-collapse-item>
            </el-collapse>
            <el-text v-if="!row.file_summary?.length" type="info">No files</el-text>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="path" label="Path" min-width="280" sortable show-overflow-tooltip />
      <el-table-column label="Size" width="110" sortable :sort-by="(row: AdminFileEntry) => row.size_bytes ?? 0">
        <template #default="{ row }">
          {{ formatBytes(row.size_bytes) }}
        </template>
      </el-table-column>
      <el-table-column label="Files" width="80" align="center" sortable :sort-by="(row: AdminFileEntry) => row.file_summary?.length ?? 0">
        <template #default="{ row }">
          <el-text type="info">{{ row.file_summary?.length ?? 0 }}</el-text>
        </template>
      </el-table-column>
      <el-table-column label="Owner" width="120" sortable prop="owner">
        <template #default="{ row }">
          <el-link v-if="row.owner" type="primary" @click="goToUserTasks(row.owner)">
            {{ row.owner }}
          </el-link>
          <el-text v-else type="info">--</el-text>
        </template>
      </el-table-column>
      <el-table-column label="Task" width="130" sortable :sort-by="(row: AdminFileEntry) => row.task_id ?? ''">
        <template #default="{ row }">
          <el-link v-if="row.task_id" type="primary" @click="goToTask(row.task_id)">
            {{ row.task_id.substring(0, 8) }}...
          </el-link>
          <el-tag v-else type="warning" size="small">orphan</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Job UUID" width="150" sortable prop="job_uuid" show-overflow-tooltip>
        <template #default="{ row }">
          <code style="font-size: 11px">{{ row.job_uuid }}</code>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="filteredEntries.length > 0" class="total-count">
      Showing {{ filteredEntries.length }} of {{ filesData?.total_entries ?? 0 }}
    </div>

    <!-- Bulk delete confirmation dialog -->
    <el-dialog
      v-model="bulkDeleteVisible"
      title="Confirm Bulk Delete"
      width="500px"
      :close-on-click-modal="false"
    >
      <p>
        Delete <strong>{{ selectedEntries.length }}</strong> directories
        ({{ formatBytes(selectedTotalSize) }})?
      </p>
      <p style="color: var(--el-color-danger)">
        This will permanently remove all files in the selected directories.
      </p>
      <el-checkbox v-model="deleteAssociatedTasks" class="cleanup-checkbox">
        Also delete associated tasks from the database
      </el-checkbox>
      <template #footer>
        <el-button @click="bulkDeleteVisible = false">Cancel</el-button>
        <el-button
          type="danger"
          :loading="deleteLoading"
          @click="handleBulkDelete"
        >
          Delete {{ selectedEntries.length }} Directories
        </el-button>
      </template>
    </el-dialog>

    <!-- Delete by name confirmation dialog -->
    <el-dialog
      v-model="deleteByNameVisible"
      title="Confirm Delete by Filename"
      width="500px"
      :close-on-click-modal="false"
    >
      <p>
        Delete all <strong>"{{ fileNameSearch }}"</strong> files from
        <strong>{{ fileNameMatchDirCount }}</strong> directories?
      </p>
      <p>
        This will free approximately
        <strong>{{ formatBytes(fileNameMatchTotalSize) }}</strong>.
      </p>
      <p style="color: var(--el-color-danger)">
        This action cannot be undone.
      </p>
      <template #footer>
        <el-button @click="deleteByNameVisible = false">Cancel</el-button>
        <el-button
          type="danger"
          :loading="deleteLoading"
          @click="handleDeleteByName"
        >
          Delete All "{{ fileNameSearch }}"
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Delete, Document, FolderOpened, RefreshRight, Search } from '@element-plus/icons-vue'
import { getAdminFiles, deleteAdminFiles, deleteAdminFilesByName } from '@/api/admin'
import type { AdminFilesResponse, AdminFileEntry, FileSummaryItem } from '@/api/types'

const router = useRouter()
const loading = ref(false)
const deleteLoading = ref(false)
const filesData = ref<AdminFilesResponse | null>(null)
const filterMode = ref<'all' | 'orphan' | 'mapped'>('all')
const searchText = ref('')
const fileNameSearch = ref('')
const selectedEntries = ref<AdminFileEntry[]>([])
const bulkDeleteVisible = ref(false)
const deleteByNameVisible = ref(false)
const deleteAssociatedTasks = ref(false)
const tableRef = ref()

// ---------------------------------------------------------------------------
// Computed: filtering
// ---------------------------------------------------------------------------

const filteredEntries = computed(() => {
  if (!filesData.value) return []
  let entries = filesData.value.entries

  // Filter by orphan/mapped mode
  if (filterMode.value === 'orphan') {
    entries = entries.filter(e => e.orphan)
  } else if (filterMode.value === 'mapped') {
    entries = entries.filter(e => !e.orphan)
  }

  // Filter by text search (owner, task_id, path)
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    entries = entries.filter(e =>
      e.path.toLowerCase().includes(q) ||
      (e.owner && e.owner.toLowerCase().includes(q)) ||
      (e.task_id && e.task_id.toLowerCase().includes(q)) ||
      e.job_uuid.toLowerCase().includes(q)
    )
  }

  // Filter by filename using basename (e.g. "WAVECAR" matches "scf_05/WAVECAR")
  if (fileNameSearch.value) {
    const fn = fileNameSearch.value.toLowerCase()
    entries = entries.filter(e =>
      e.file_summary?.some(f => {
        const bn = f.name.includes('/') ? f.name.split('/').pop()! : f.name
        return bn.toLowerCase().includes(fn)
      })
    )
  }

  return entries
})

// ---------------------------------------------------------------------------
// Computed: file type statistics
// ---------------------------------------------------------------------------

interface FileTypeStat {
  name: string
  totalSize: number
  count: number
}

const fileTypeStats = computed<FileTypeStat[]>(() => {
  if (!filesData.value) return []

  const statMap = new Map<string, { totalSize: number; count: number }>()

  for (const entry of filesData.value.entries) {
    if (!entry.file_summary) continue
    for (const file of entry.file_summary) {
      // Use basename for grouping (e.g. "scf_05/WAVECAR" → "WAVECAR")
      const basename = file.name.includes('/') ? file.name.split('/').pop()! : file.name
      const existing = statMap.get(basename)
      if (existing) {
        existing.totalSize += file.size
        existing.count += 1
      } else {
        statMap.set(basename, { totalSize: file.size, count: 1 })
      }
    }
  }

  // Sort by total size descending, keep top entries
  return Array.from(statMap.entries())
    .map(([name, stat]) => ({ name, ...stat }))
    .filter(s => s.count > 1 || s.totalSize > 1024 * 1024) // Show if >1 file or >1MB
    .sort((a, b) => b.totalSize - a.totalSize)
    .slice(0, 20)
})

// ---------------------------------------------------------------------------
// Computed: filename search stats
// ---------------------------------------------------------------------------

function _basename(name: string): string {
  return name.includes('/') ? name.split('/').pop()! : name
}

const fileNameMatchCount = computed(() => {
  if (!fileNameSearch.value || !filesData.value) return 0
  const fn = fileNameSearch.value.toLowerCase()
  let count = 0
  for (const entry of filesData.value.entries) {
    if (!entry.file_summary) continue
    count += entry.file_summary.filter(f =>
      _basename(f.name).toLowerCase().includes(fn)
    ).length
  }
  return count
})

const fileNameMatchDirCount = computed(() => {
  return filteredEntries.value.length
})

const fileNameMatchTotalSize = computed(() => {
  if (!fileNameSearch.value) return 0
  const fn = fileNameSearch.value.toLowerCase()
  let total = 0
  for (const entry of filteredEntries.value) {
    if (!entry.file_summary) continue
    for (const file of entry.file_summary) {
      if (_basename(file.name).toLowerCase().includes(fn)) {
        total += file.size
      }
    }
  }
  return total
})

// ---------------------------------------------------------------------------
// Computed: selection
// ---------------------------------------------------------------------------

const uniqueTaskCount = computed(() => {
  if (!filesData.value) return 0
  const taskIds = new Set(
    filesData.value.entries
      .map(e => e.task_id)
      .filter((id): id is string => id != null)
  )
  return taskIds.size
})

const selectedTotalSize = computed(() => {
  return selectedEntries.value.reduce(
    (sum, e) => sum + (e.size_bytes ?? 0), 0
  )
})

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

onMounted(() => {
  loadFiles()
})

async function loadFiles(forceRefresh: boolean = false): Promise<void> {
  loading.value = true
  try {
    filesData.value = await getAdminFiles(forceRefresh)
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Failed to load files')
  } finally {
    loading.value = false
  }
}

// ---------------------------------------------------------------------------
// Event handlers
// ---------------------------------------------------------------------------

function handleSelectionChange(selection: AdminFileEntry[]): void {
  selectedEntries.value = selection
}

function handleStatTagClick(name: string): void {
  // Toggle: if already filtering by this name, clear it
  if (fileNameSearch.value === name) {
    fileNameSearch.value = ''
  } else {
    fileNameSearch.value = name
  }
}

function goToUserTasks(owner: string): void {
  router.push({ name: 'admin-tasks', query: { owner } })
}

function goToTask(taskId: string): void {
  router.push({ name: 'task-detail', params: { taskId } })
}

// ---------------------------------------------------------------------------
// File display helpers
// ---------------------------------------------------------------------------

interface GroupedFiles {
  root: FileSummaryItem[]
  subdirs: Record<string, FileSummaryItem[]>
}

function getGroupedFiles(row: AdminFileEntry): GroupedFiles {
  const files = row.file_summary ?? []
  const root: FileSummaryItem[] = []
  const subdirs: Record<string, FileSummaryItem[]> = {}

  for (const f of files) {
    if (f.name.includes('/')) {
      const parts = f.name.split('/')
      const dir = parts.slice(0, -1).join('/')
      if (!subdirs[dir]) subdirs[dir] = []
      subdirs[dir].push(f)
    } else {
      root.push(f)
    }
  }
  return { root, subdirs }
}

function basename(name: string): string {
  return name.includes('/') ? name.split('/').pop()! : name
}

function isFileNameMatch(name: string): boolean {
  if (!fileNameSearch.value) return false
  // Match against basename so "WAVECAR" matches "scf_05/WAVECAR"
  return basename(name).toLowerCase().includes(fileNameSearch.value.toLowerCase())
}

function fileIconClass(filename: string): string {
  // Return a CSS class based on file type for visual grouping
  const lower = basename(filename).toLowerCase()
  if (['wavecar', 'chgcar', 'chg'].includes(lower)) return 'icon-large-file'
  if (['incar', 'poscar', 'kpoints', 'potcar'].includes(lower)) return 'icon-input-file'
  if (lower.endsWith('.png') || lower.endsWith('.jpg')) return 'icon-image-file'
  return ''
}

// ---------------------------------------------------------------------------
// Delete: single file
// ---------------------------------------------------------------------------

async function handleDeleteSingleFile(
  dirEntry: AdminFileEntry,
  file: FileSummaryItem
): Promise<void> {
  const filePath = `${dirEntry.abs_path}/${file.name}`
  try {
    const result = await deleteAdminFiles({
      targets: [{ abs_path: filePath }],
      delete_associated_tasks: false,
    })
    if (result.deleted > 0) {
      ElMessage.success(`Deleted ${file.name}`)
      // Update local state: remove from file_summary and update size
      const idx = dirEntry.file_summary.findIndex(f => f.name === file.name)
      if (idx >= 0) {
        const deletedSize = dirEntry.file_summary[idx].size
        dirEntry.file_summary.splice(idx, 1)
        if (dirEntry.size_bytes != null) {
          dirEntry.size_bytes -= deletedSize
        }
      }
    } else if (result.failed.length > 0) {
      ElMessage.error(`Failed: ${result.failed[0].error}`)
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Delete failed')
  }
}

// ---------------------------------------------------------------------------
// Delete: bulk directories
// ---------------------------------------------------------------------------

function confirmBulkDelete(): void {
  bulkDeleteVisible.value = true
}

async function handleBulkDelete(): Promise<void> {
  deleteLoading.value = true
  try {
    const targets = selectedEntries.value.map(e => ({
      abs_path: e.abs_path,
      task_id: e.task_id,
    }))
    const result = await deleteAdminFiles({
      targets,
      delete_associated_tasks: deleteAssociatedTasks.value,
    })
    const msg = result.failed.length > 0
      ? `Deleted ${result.deleted}, failed ${result.failed.length}`
      : `Deleted ${result.deleted} directories`
    ElMessage.success(msg)
    bulkDeleteVisible.value = false
    selectedEntries.value = []
    await loadFiles()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Bulk delete failed')
  } finally {
    deleteLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// Delete: by filename
// ---------------------------------------------------------------------------

function confirmDeleteByName(): void {
  deleteByNameVisible.value = true
}

async function handleDeleteByName(): Promise<void> {
  if (!fileNameSearch.value) return
  deleteLoading.value = true
  try {
    const jobDirs = filteredEntries.value.map(e => e.abs_path)
    const result = await deleteAdminFilesByName({
      filename: fileNameSearch.value,
      job_dirs: jobDirs,
    })
    const msg = result.failed.length > 0
      ? `Deleted ${result.deleted}, failed ${result.failed.length}`
      : `Deleted ${result.deleted} files`
    ElMessage.success(msg)
    deleteByNameVisible.value = false
    await loadFiles()
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Delete by name failed')
  } finally {
    deleteLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return '--'
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const k = 1024
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  const value = bytes / Math.pow(k, i)
  return `${value.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}
</script>

<style scoped>
.files-page {
  max-width: 1400px;
}

.page-heading {
  margin: 0 0 20px;
  font-size: 20px;
  color: var(--el-text-color-primary);
}

.stats-card {
  margin-bottom: 12px;
}

.stats-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.stats-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.stats-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.stat-tag {
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.stat-tag:hover {
  opacity: 0.8;
}

.summary-card {
  margin-bottom: 16px;
}

.summary-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.summary-spacer {
  flex: 1;
}

.search-summary {
  margin-top: 10px;
}

.selection-bar {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: var(--el-color-info-light-9);
  border-radius: 4px;
}

.files-table {
  width: 100%;
}

.expand-content {
  padding: 4px 16px 4px 48px;
}

.file-group-files {
  display: flex;
  flex-direction: column;
}

.file-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 4px 8px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.file-row:last-child {
  border-bottom: none;
}

.file-row .file-entry {
  flex: 1;
  min-width: 0;
}

.file-size {
  width: 80px;
  text-align: right;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  flex-shrink: 0;
}

.subdir-collapse {
  margin-top: 4px;
}

.subdir-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
}

:deep(.subdir-collapse .el-collapse-item__content) {
  padding: 0 8px;
}

.file-entry {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.file-icon {
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

.file-icon.icon-large-file {
  color: var(--el-color-warning);
}

.file-icon.icon-input-file {
  color: var(--el-color-primary);
}

.file-icon.icon-image-file {
  color: var(--el-color-success);
}

.highlight-match {
  background-color: var(--el-color-warning-light-7);
  padding: 1px 4px;
  border-radius: 3px;
  font-weight: 600;
}

.total-count {
  margin-top: 12px;
  text-align: right;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.cleanup-checkbox {
  margin-top: 12px;
}
</style>
