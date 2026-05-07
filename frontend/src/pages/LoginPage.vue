<template>
  <div class="login-page">
    <el-card class="login-card">
      <template #header>
        <div class="login-brand">
          <!-- Inline QDYN mark SVG -->
          <svg
            class="login-brand__mark"
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
          <span class="login-brand__text">QDYN</span>
          <span class="login-brand__tagline">Quantum dynamics, on cluster.</span>
        </div>
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
  background-color: var(--bg-page);
}

/* Subtle dot-grid background pattern at 10% opacity */
.login-page::before {
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

.login-card {
  position: relative;
  z-index: 1;
  width: 100%;
  max-width: 400px;
  background: var(--bg-surface);
  border-radius: var(--radius-lg);
}

.login-brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.login-brand__mark {
  color: var(--brand-primary);
}

.login-brand__text {
  font-weight: 600;
  font-size: 22px;
  letter-spacing: 2px;
  color: var(--fg-primary);
}

.login-brand__tagline {
  font-family: var(--font-display);
  font-style: italic;
  font-size: var(--fs-14);
  color: var(--fg-tertiary);
}

.login-button {
  width: 100%;
}

.register-link {
  text-align: center;
  margin-top: 16px;
  color: var(--fg-tertiary);
}
</style>
