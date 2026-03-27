<template>
  <div class="register-page">
    <el-card class="register-card">
      <template #header>
        <h2 class="register-title">QDYN Register</h2>
      </template>

      <el-form
        ref="formRef"
        :model="formData"
        :rules="formRules"
        label-position="top"
        @submit.prevent="handleRegister"
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

        <el-form-item label="Confirm Password" prop="confirmPassword">
          <el-input
            v-model="formData.confirmPassword"
            type="password"
            placeholder="Confirm password"
            show-password
            :disabled="loading"
          />
        </el-form-item>

        <el-form-item>
          <el-button
            type="primary"
            native-type="submit"
            :loading="loading"
            class="register-button"
          >
            Register
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-link">
        <span>Already have an account?</span>
        <el-button type="primary" link @click="goToLogin">
          Login here
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
  password: '',
  confirmPassword: ''
})

const validateConfirmPassword = (
  _rule: unknown,
  value: string,
  callback: (error?: Error) => void
): void => {
  if (value !== formData.password) {
    callback(new Error('Passwords do not match'))
  } else {
    callback()
  }
}

const formRules: FormRules = {
  username: [
    { required: true, message: 'Please enter username', trigger: 'blur' },
    { min: 3, message: 'Username must be at least 3 characters', trigger: 'blur' }
  ],
  password: [
    { required: true, message: 'Please enter password', trigger: 'blur' },
    { min: 6, message: 'Password must be at least 6 characters', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, message: 'Please confirm password', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' }
  ]
}

async function handleRegister(): Promise<void> {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return

  loading.value = true
  try {
    await authStore.register(formData.username, formData.password)
    ElMessage.success('Registration successful')

    // Redirect to original page or task list
    const redirect = route.query.redirect as string
    router.push(redirect || { name: 'task-list' })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Registration failed'
    ElMessage.error(message)
  } finally {
    loading.value = false
  }
}

function goToLogin(): void {
  router.push({ name: 'login' })
}
</script>

<style scoped>
.register-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background-color: var(--el-bg-color-page);
}

.register-card {
  width: 100%;
  max-width: 400px;
}

.register-title {
  text-align: center;
  margin: 0;
  color: var(--el-text-color-primary);
}

.register-button {
  width: 100%;
}

.login-link {
  text-align: center;
  margin-top: 16px;
  color: var(--el-text-color-secondary);
}
</style>
