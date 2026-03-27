<template>
  <div class="login-page">
    <el-card class="login-card">
      <template #header>
        <h2 class="login-title">QDYN Login</h2>
      </template>

      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-position="top"
        @submit.prevent="handleLogin"
      >
        <el-form-item label="Username" prop="username">
          <el-input
            v-model="formData.username"
            placeholder="Enter username"
            :disabled="loading"
          />
        </el-form-item>

        <el-form-item label="Password" prop="password">
          <el-input
            v-model="formData.password"
            type="password"
            placeholder="Enter password"
            show-password
            :disabled="loading"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            native-type="submit"
            :loading="loading"
            class="login-button"
          >
            Login
          </el-button>
        </el-form-item>
      </el-form>

      <div class="register-link">
        <span>No account?</span>
        <el-button type="primary" link @click="goToRegister">
          Register here
        </el-button>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)

const formData = reactive({
  username: '',
  password: ''
})

const formRules: FormRules = {
  username: [
    { required: true, message: 'Please enter username', trigger: 'blur' }
  ],
  password: [
    { required: true, message: 'Please enter password', trigger: 'blur' }
  ]
}

async function handleLogin(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await authStore.login(formData.username, formData.password)
    ElMessage.success('Login successful')

    // Redirect to original page or task list
    const redirect = route.query.redirect as string
    router.push(redirect || { name: 'task-list' })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Login failed'
    ElMessage.error(message)
  } finally {
    loading.value = false
  }
}

function goToRegister(): void {
  router.push({ name: 'register' })
}
</script>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background-color: var(--el-bg-color-page);
}

.login-card {
  width: 100%;
  max-width: 400px;
}

.login-title {
  text-align: center;
  margin: 0;
  color: var(--el-text-color-primary);
}

.login-button {
  width: 100%;
}

.register-link {
  text-align: center;
  margin-top: 16px;
  color: var(--el-text-color-secondary);
}
</style>
