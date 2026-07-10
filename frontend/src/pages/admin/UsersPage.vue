<template>
  <div class="users-page">
    <h2 class="page-heading">User Management</h2>

    <el-table
      v-loading="loading"
      :data="users"
      stripe
      class="users-table"
    >
      <el-table-column label="Username" min-width="150">
        <template #default="{ row }">
          <el-link type="primary" @click="goToUserTasks(row.username)">
            {{ row.username }}
          </el-link>
        </template>
      </el-table-column>
      <el-table-column label="Role" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.is_admin" type="danger" size="small" effect="dark">Admin</el-tag>
          <el-tag v-else type="info" size="small" effect="plain">User</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="Created" width="180">
        <template #default="{ row }">
          {{ formatTimestamp(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column prop="task_count" label="Tasks" width="100" align="center" />
      <el-table-column label="Actions" width="220" fixed="right">
        <template #default="{ row }">
          <div class="action-buttons">
            <!-- Toggle admin role -->
            <el-button
              :type="row.is_admin ? 'warning' : 'success'"
              plain
              size="small"
              @click="handleToggleAdmin(row)"
            >
              {{ row.is_admin ? 'Revoke Admin' : 'Grant Admin' }}
            </el-button>

            <!-- Reset password -->
            <el-button
              type="primary"
              plain
              size="small"
              @click="openResetPasswordDialog(row.username)"
            >
              Reset Password
            </el-button>

            <!-- Delete user -->
            <el-popconfirm
              :title="`Delete user '${row.username}'? This will stop all running jobs and remove all task records.`"
              confirm-button-text="Delete"
              cancel-button-text="Cancel"
              confirm-button-type="danger"
              @confirm="handleDeleteUser(row.username)"
            >
              <template #reference>
                <el-button type="danger" plain size="small">
                  Delete
                </el-button>
              </template>
            </el-popconfirm>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <!-- Reset Password Dialog -->
    <el-dialog
      v-model="resetPasswordVisible"
      title="Reset Password"
      width="400px"
      :close-on-click-modal="false"
    >
      <el-form
        ref="resetFormRef"
        :model="resetForm"
        :rules="resetFormRules"
        label-position="top"
        @submit.prevent="handleResetPassword"
      >
        <el-form-item label="Username">
          <el-input :model-value="resetForm.username" disabled />
        </el-form-item>
        <el-form-item label="New Password" prop="password">
          <el-input
            v-model="resetForm.password"
            type="password"
            placeholder="Enter new password"
            show-password
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetPasswordVisible = false">Cancel</el-button>
        <el-button
          type="primary"
          :loading="resettingPassword"
          @click="handleResetPassword"
        >
          Reset
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { getAdminUsers, resetUserPassword, setUserRole, deleteUser } from '@/api/admin'
import type { AdminUserItem } from '@/api/types'

const router = useRouter()

const users = ref<AdminUserItem[]>([])
const loading = ref(false)

// Reset password dialog state
const resetPasswordVisible = ref(false)
const resettingPassword = ref(false)
const resetFormRef = ref<FormInstance>()
const resetForm = reactive({
  username: '',
  password: ''
})

const resetFormRules: FormRules = {
  password: [
    { required: true, message: 'Please enter a new password', trigger: 'blur' },
    { min: 4, message: 'Password must be at least 4 characters', trigger: 'blur' }
  ]
}

onMounted(() => {
  loadUsers()
})

async function loadUsers(): Promise<void> {
  loading.value = true
  try {
    users.value = await getAdminUsers()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load users'
    ElMessage.error(message)
  } finally {
    loading.value = false
  }
}

function goToUserTasks(username: string): void {
  router.push({ name: 'admin-tasks', query: { owner: username } })
}

function formatTimestamp(ts: number | null): string {
  if (ts === null || Number.isNaN(ts)) return '—'
  return new Date(ts * 1000).toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

function openResetPasswordDialog(username: string): void {
  resetForm.username = username
  resetForm.password = ''
  resetPasswordVisible.value = true
}

async function handleResetPassword(): Promise<void> {
  const valid = await resetFormRef.value?.validate().catch(() => false)
  if (!valid) return

  resettingPassword.value = true
  try {
    await resetUserPassword(resetForm.username, resetForm.password)
    ElMessage.success(`Password for '${resetForm.username}' has been reset`)
    resetPasswordVisible.value = false
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to reset password'
    ElMessage.error(message)
  } finally {
    resettingPassword.value = false
  }
}

async function handleToggleAdmin(user: AdminUserItem): Promise<void> {
  try {
    await setUserRole(user.username, !user.is_admin)
    ElMessage.success(
      user.is_admin
        ? `Removed admin privileges from '${user.username}'`
        : `Granted admin privileges to '${user.username}'`
    )
    // Refresh user list to reflect changes
    await loadUsers()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to update role'
    ElMessage.error(message)
  }
}

async function handleDeleteUser(username: string): Promise<void> {
  try {
    await deleteUser(username)
    ElMessage.success(`User '${username}' has been deleted`)
    // Refresh user list
    await loadUsers()
  } catch (err: unknown) {
    // Check for 409 Conflict (user has DISPATCHING tasks)
    let message = 'Failed to delete user'
    if (err && typeof err === 'object' && 'response' in err) {
      const axiosErr = err as { response?: { status?: number; data?: { detail?: string } } }
      if (axiosErr.response?.status === 409) {
        message = axiosErr.response.data?.detail || 'User has dispatching tasks. Please wait and try again.'
      }
    } else if (err instanceof Error) {
      message = err.message
    }
    ElMessage.error(message)
  }
}
</script>

<style scoped>
.users-page {
  max-width: 1200px;
}

.page-heading {
  margin: 0 0 20px;
  font-size: 20px;
  color: var(--el-text-color-primary);
}

.users-table {
  width: 100%;
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}

/* el-popconfirm renders a wrapper element around its trigger button;
   make it behave like a plain flex item so it aligns with sibling buttons. */
.action-buttons :deep(.el-popconfirm) {
  display: inline-flex;
}

.action-buttons :deep(.el-button) {
  margin-left: 0;
}
</style>
