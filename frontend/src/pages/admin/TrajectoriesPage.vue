<template>
  <div class="trajectories-page">
    <h2 class="page-heading">Trajectories</h2>

    <!-- Summary bar -->
    <el-row class="summary-bar" :gutter="16">
      <el-col :span="8">
        <el-statistic title="Total Files" :value="trajData?.total ?? 0" />
      </el-col>
      <el-col :span="8">
        <el-statistic title="Total Size" :value="formatBytes(trajData?.total_bytes ?? 0)" />
      </el-col>
      <el-col :span="8">
        <el-button type="primary" :loading="loading" @click="fetchTrajectories">
          Refresh
        </el-button>
        <el-button
          type="danger"
          :disabled="selectedRows.length === 0"
          @click="handleBulkDelete"
        >
          Delete Selected ({{ selectedRows.length }})
        </el-button>
      </el-col>
    </el-row>

    <!-- Trajectory table -->
    <el-table
      v-loading="loading"
      :data="trajData?.items ?? []"
      stripe
      class="traj-table"
      @selection-change="handleSelectionChange"
    >
      <el-table-column type="selection" width="42" />
      <el-table-column label="Hash" prop="hash" min-width="140">
        <template #default="{ row }">
          <el-tooltip :content="row.hash" placement="top">
            <code class="hash-cell">{{ row.hash.slice(0, 8) }}...</code>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="Formula" prop="formula" width="120">
        <template #default="{ row }">
          {{ row.formula ?? '-' }}
        </template>
      </el-table-column>
      <el-table-column label="Atoms" prop="num_atoms" width="80" align="right">
        <template #default="{ row }">
          {{ row.num_atoms ?? '-' }}
        </template>
      </el-table-column>
      <el-table-column label="Frames" prop="num_frames" width="80" align="right">
        <template #default="{ row }">
          {{ row.num_frames ?? '-' }}
        </template>
      </el-table-column>
      <el-table-column label="Size" prop="size_bytes" width="100" align="right" sortable>
        <template #default="{ row }">
          {{ formatBytes(row.size_bytes) }}
        </template>
      </el-table-column>
      <el-table-column label="Created" prop="created_at" width="160" sortable />
      <el-table-column label="Refs" prop="ref_count" width="70" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.ref_count > 0" type="warning" size="small">
            {{ row.ref_count }}
          </el-tag>
          <span v-else>0</span>
        </template>
      </el-table-column>
      <el-table-column label="Actions" width="100" align="center">
        <template #default="{ row }">
          <el-popconfirm
            v-if="row.ref_count > 0"
            title="This file is still referenced by submissions. Force delete?"
            confirm-button-text="Force Delete"
            cancel-button-text="Cancel"
            confirm-button-type="danger"
            @confirm="handleDelete(row.hash, true)"
          >
            <template #reference>
              <el-button type="danger" size="small" link>Delete</el-button>
            </template>
          </el-popconfirm>
          <el-popconfirm
            v-else
            title="Are you sure you want to delete this file?"
            @confirm="handleDelete(row.hash, false)"
          >
            <template #reference>
              <el-button type="danger" size="small" link>Delete</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getAdminTrajectories, deleteTrajectory } from '@/api/admin'
import type { TrajListResponse, TrajFileItem } from '@/api/types'

const loading = ref(false)
const trajData = ref<TrajListResponse | null>(null)
const selectedRows = ref<TrajFileItem[]>([])

function formatBytes(bytes: number | string): string {
  const n = typeof bytes === 'string' ? parseFloat(bytes) : bytes
  if (n === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(n) / Math.log(k))
  return parseFloat((n / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

async function fetchTrajectories() {
  loading.value = true
  try {
    trajData.value = await getAdminTrajectories()
  } catch (err: any) {
    ElMessage.error('Failed to load trajectories: ' + (err.message || err))
  } finally {
    loading.value = false
  }
}

function handleSelectionChange(rows: TrajFileItem[]) {
  selectedRows.value = rows
}

async function handleDelete(hash: string, force: boolean) {
  try {
    await deleteTrajectory(hash, force)
    ElMessage.success('Trajectory deleted')
    await fetchTrajectories()
  } catch (err: any) {
    const detail = err.response?.data?.detail || err.message || err
    ElMessage.error('Delete failed: ' + detail)
  }
}

async function handleBulkDelete() {
  const hasRefs = selectedRows.value.some(r => r.ref_count > 0)
  const msg = hasRefs
    ? `Delete ${selectedRows.value.length} file(s)? Some are still referenced.`
    : `Delete ${selectedRows.value.length} file(s)?`

  try {
    // Use ElMessageBox for confirmation
    const { ElMessageBox } = await import('element-plus')
    await ElMessageBox.confirm(msg, 'Confirm Bulk Delete', {
      confirmButtonText: 'Delete',
      cancelButtonText: 'Cancel',
      type: 'warning'
    })
  } catch {
    return // cancelled
  }

  let success = 0
  let failed = 0
  for (const row of selectedRows.value) {
    try {
      await deleteTrajectory(row.hash, true)
      success++
    } catch {
      failed++
    }
  }
  ElMessage.info(`Deleted ${success}, failed ${failed}`)
  await fetchTrajectories()
}

onMounted(fetchTrajectories)
</script>

<style scoped>
.trajectories-page {
  padding: 0;
}

.page-heading {
  margin-top: 0;
  margin-bottom: 20px;
}

.summary-bar {
  margin-bottom: 20px;
  align-items: center;
}

.traj-table {
  width: 100%;
}

.hash-cell {
  font-family: 'Courier New', Courier, monospace;
  font-size: 13px;
}
</style>
