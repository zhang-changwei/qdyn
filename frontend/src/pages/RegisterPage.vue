<template>
  <div class="register-page">
    <el-card class="register-card">
      <template #header>
        <div class="register-brand">
          <!-- Inline QDYN mark SVG -->
          <svg
            class="register-brand__mark"
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 64 64"
            width="48"
            height="48"
            fill="none"
            stroke="currentColor"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-label="QDYN mark"
          >
            <g opacity="0.16" fill="currentColor" stroke="none">
              <circle cx="10" cy="10" r="6" />
              <circle cx="32" cy="10" r="6" />
              <circle cx="54" cy="10" r="6" />
              <circle cx="10" cy="32" r="6" />
              <circle cx="54" cy="32" r="6" />
              <circle cx="10" cy="54" r="6" />
              <circle cx="32" cy="54" r="6" />
              <circle cx="54" cy="54" r="6" />
            </g>
            <g stroke-width="1" stroke-dasharray="1.8 2" opacity="0.5">
              <line x1="14" y1="14" x2="25" y2="25" />
              <line x1="32" y1="14" x2="32" y2="22" />
              <line x1="50" y1="14" x2="39" y2="25" />
              <line x1="14" y1="32" x2="22" y2="32" />
              <line x1="50" y1="32" x2="42" y2="32" />
              <line x1="14" y1="50" x2="25" y2="39" />
              <line x1="32" y1="50" x2="32" y2="42" />
              <line x1="50" y1="50" x2="39" y2="39" />
            </g>
            <g fill="currentColor" stroke="none">
              <circle cx="32" cy="32" r="13" opacity="0.07" />
              <circle cx="32" cy="32" r="9" opacity="0.13" />
              <circle cx="32" cy="32" r="6" opacity="0.22" />
              <circle cx="32" cy="32" r="3" opacity="0.32" />
            </g>
            <g fill="currentColor" stroke="none">
              <circle cx="10" cy="10" r="3.5" />
              <circle cx="32" cy="10" r="3.5" />
              <circle cx="54" cy="10" r="3.5" />
              <circle cx="10" cy="32" r="3.5" />
              <circle cx="54" cy="32" r="3.5" />
              <circle cx="10" cy="54" r="3.5" />
              <circle cx="32" cy="54" r="3.5" />
              <circle cx="54" cy="54" r="3.5" />
            </g>
          </svg>
          <span class="register-brand__text">QDYN</span>
          <span class="register-brand__tagline">Quantum dynamics, on cluster.</span>
        </div>
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
  background-color: var(--bg-page);
}

/* Dot-grid background pattern */
.register-page::before {
  content: '';
  position: fixed;
  inset: 0;
  background-color: var(--bg-page);
  background-image: radial-gradient(circle, var(--fg-tertiary) 1px, transparent 1px);
  background-size: 24px 24px;
  background-position: 12px 12px;
  opacity: 0.10;
  z-index: 0;
  pointer-events: none;
}

.register-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 400px;
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
}

.register-brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.register-brand__mark {
  color: var(--brand-primary);
}

.register-brand__text {
  font-weight: 600;
  font-size: 22px;
  letter-spacing: 2px;
  color: var(--fg-primary);
}

.register-brand__tagline {
  font-family: var(--font-display);
  font-style: italic;
  font-size: var(--fs-14);
  color: var(--fg-tertiary);
}

.register-button {
  width: 100%;
}

.login-link {
  text-align: center;
  margin-top: 16px;
  color: var(--fg-tertiary);
}
</style>
