<template>
  <div class="files-page">
    <h2 class="page-heading">File Browser</h2>

    <!-- Index status alert -->
    <el-alert
      v-if="indexStatus === 'building'"
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    >
      <template #title>
        File index is building in the background. File counts, sizes, search
        and stats will be available shortly.
      </template>
    </el-alert>
    <el-alert
      v-else-if="indexStatus === 'error'"
      type="error"
      :closable="false"
      show-icon
      style="margin-bottom: 12px"
    >
      <template #title>
        File index error: {{ indexError ?? 'unknown' }}
      </template>
      <template #default>
        <el-button type="danger" size="small" plain @click="loadFiles(true)">
          Retry
        </el-button>
      </template>
    </el-alert>

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
          :placeholder="indexStatus === 'ready' ? 'Search filenames (e.g. WAVECAR)' : 'Index building...'"
          clearable
          :disabled="indexStatus !== 'ready'"
          style="width: 260px"
          @change="handleFileNameSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>
      </div>

      <!-- File name search results summary -->
      <div v-if="fileNameSearch && searchResults.length > 0" class="search-summary">
        <el-alert type="info" :closable="false" show-icon>
          <template #title>
            Found <strong>{{ searchResults.length }}</strong> matching files
            in <strong>{{ searchResultDirCount }}</strong> directories
            ({{ formatBytes(searchResultTotalSize) }} total)
          </template>
          <template v-if="searchResultDirCount > 0" #default>
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
      @expand-change="handleExpandChange"
    >
      <el-table-column type="selection" width="40" />
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="expand-content">
            <div v-if="expandedLoading[row.abs_path]" v-loading="true" class="expand-loading" />
            <template v-else-if="getGroupedFiles(row).root.length > 0 || Object.keys(getGroupedFiles(row).subdirs).length > 0">
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
                      <el-tag size="small">{{ formatBytes(files.reduce((s, f) => s + f.size, 0)) }}</el-tag>
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
            </template>
            <el-text v-else type="info">No files</el-text>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="path" label="Path" min-width="280" sortable show-overflow-tooltip />
      <el-table-column label="Size" width="110" sortable :sort-by="sortBySize">
        <template #default="{ row }">
          {{ row.size_bytes != null ? formatBytes(row.size_bytes) : '—' }}
        </template>
      </el-table-column>
      <el-table-column label="Files" width="80" align="center" sortable :sort-by="sortByFileCount">
        <template #default="{ row }">
          <el-text type="info">{{ row.file_count ?? '—' }}</el-text>
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
      <el-table-column label="Task" width="130" sortable :sort-by="sortByTaskId">
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
        <strong>{{ searchResultDirCount }}</strong> directories?
      </p>
      <p>
        This will free approximately
        <strong>{{ formatBytes(searchResultTotalSize) }}</strong>.
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
import { ref, computed, onMounted, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Delete, Document, FolderOpened, RefreshRight, Search } from '@element-plus/icons-vue'
import {
  getAdminFiles,
  deleteAdminFiles,
  deleteAdminFilesByName,
  searchFiles,
  getFileTypeStats,
  getLeafFileSummary,
} from '@/api/admin'
import type {
  AdminFilesResponse,
  AdminFileEntry,
  FileSummaryItem,
  FileTypeStat,
  FileSearchResultItem,
} from '@/api/types'

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

// File index status from backend.
const indexStatus = ref<string>('building')
const indexError = ref<string | null>(null)

// Lazy-loaded file summaries for expanded rows: abs_path -> FileSummaryItem[]
const expandedSummaries = reactive<Record<string, FileSummaryItem[]>>({})
const expandedLoading = reactive<Record<string, boolean>>({})

// Backend search results for fileNameSearch.
const searchResults = ref<FileSearchResultItem[]>([])

// Backend file type stats.
const fileTypeStats = ref<FileTypeStat[]>([])

// ---------------------------------------------------------------------------
// Computed: index readiness
// ---------------------------------------------------------------------------

const indexReady = computed(() => indexStatus.value === 'ready')

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

  // Filter by text search (owner, task_id, path, job_uuid)
  if (searchText.value) {
    const q = searchText.value.toLowerCase()
    entries = entries.filter(e =>
      e.path.toLowerCase().includes(q) ||
      (e.owner && e.owner.toLowerCase().includes(q)) ||
      (e.task_id && e.task_id.toLowerCase().includes(q)) ||
      e.job_uuid.toLowerCase().includes(q)
    )
  }

  // Filter by filename search using backend search results.
  // When fileNameSearch is non-empty, only show leaf dirs that appear in
  // the search results.  An empty result set naturally yields an empty
  // table (showing "no matches"), rather than falling back to all dirs.
  if (fileNameSearch.value) {
    const matchingPaths = new Set(searchResults.value.map(r => r.leaf_path))
    entries = entries.filter(e => matchingPaths.has(e.path))
  }

  return entries
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
// Computed: filename search stats (from backend results)
// ---------------------------------------------------------------------------

const searchResultDirCount = computed(() => {
  if (!fileNameSearch.value) return 0
  return new Set(searchResults.value.map(r => r.leaf_path)).size
})

const searchResultTotalSize = computed(() => {
  if (!fileNameSearch.value) return 0
  return searchResults.value.reduce((sum, r) => sum + r.size, 0)
})

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

onMounted(() => {
  loadFiles()
  loadFileTypeStats()
})

async function loadFiles(forceRefresh: boolean = false): Promise<void> {
  loading.value = true
  try {
    filesData.value = await getAdminFiles(forceRefresh)
    indexStatus.value = filesData.value.index_status ?? 'building'
    // Clear expanded summaries on reload.
    Object.keys(expandedSummaries).forEach(k => delete expandedSummaries[k])
    Object.keys(expandedLoading).forEach(k => delete expandedLoading[k])
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Failed to load files')
  } finally {
    loading.value = false
  }
}

async function loadFileTypeStats(): Promise<void> {
  try {
    const resp = await getFileTypeStats()
    fileTypeStats.value = resp.stats
      .filter(s => s.count > 1 || s.totalSize > 1024 * 1024)
      .sort((a, b) => b.totalSize - a.totalSize)
      .slice(0, 20)
  } catch {
    // Stats are non-critical; silently ignore.
  }
}

async function handleFileNameSearch(): Promise<void> {
  if (!fileNameSearch.value || !indexReady.value) {
    searchResults.value = []
    return
  }
  try {
    const resp = await searchFiles(fileNameSearch.value)
    searchResults.value = resp.results
  } catch {
    searchResults.value = []
  }
}

// ---------------------------------------------------------------------------
// Lazy expand: fetch file summary on row expand
// ---------------------------------------------------------------------------

async function handleExpandChange(row: AdminFileEntry, expandedRows: AdminFileEntry[]): Promise<void> {
  const isExpanded = expandedRows.some(r => r.abs_path === row.abs_path)
  if (!isExpanded) return
  // Already loaded?
  if (expandedSummaries[row.abs_path] || expandedLoading[row.abs_path]) return

  expandedLoading[row.abs_path] = true
  try {
    const resp = await getLeafFileSummary(row.path)
    if (resp.file_summary) {
      expandedSummaries[row.abs_path] = resp.file_summary
    }
  } catch {
    ElMessage.error('Failed to load file details')
  } finally {
    expandedLoading[row.abs_path] = false
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
    searchResults.value = []
  } else {
    fileNameSearch.value = name
    handleFileNameSearch()
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
  const files = expandedSummaries[row.abs_path] ?? []
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
  return basename(name).toLowerCase().includes(fileNameSearch.value.toLowerCase())
}

function fileIconClass(filename: string): string {
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
      // Optimistic update: remove from expanded summary, decrement file_count,
      // subtract size_bytes, and trigger background index refresh.
      const summary = expandedSummaries[dirEntry.abs_path]
      if (summary) {
        const idx = summary.findIndex(f => f.name === file.name)
        if (idx >= 0) {
          summary.splice(idx, 1)
        }
      }
      if (dirEntry.file_count != null && dirEntry.file_count > 0) {
        dirEntry.file_count--
      }
      if (dirEntry.size_bytes != null) {
        dirEntry.size_bytes -= file.size
      }
      // Trigger background refresh of the file index.
      // The backend delete endpoint already calls invalidate_files_cache().
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
    await loadFileTypeStats()
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
    await loadFileTypeStats()
    if (fileNameSearch.value) {
      await handleFileNameSearch()
    }
  } catch (err) {
    ElMessage.error(err instanceof Error ? err.message : 'Delete by name failed')
  } finally {
    deleteLoading.value = false
  }
}

// ---------------------------------------------------------------------------
// Sort helpers (extracted from template to avoid inline type annotations
// which break vue-tsc template analysis for noUnusedLocals)
// ---------------------------------------------------------------------------

function sortBySize(row: AdminFileEntry): number {
  return row.size_bytes ?? 0
}

function sortByFileCount(row: AdminFileEntry): number {
  return row.file_count ?? 0
}

function sortByTaskId(row: AdminFileEntry): string {
  return row.task_id ?? ''
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

.expand-loading {
  height: 60px;
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
