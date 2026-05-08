<template>
  <header class="app-header">
    <div class="app-header__inner">
      <router-link to="/" class="app-header__brand">
        <!-- Inline QDYN mark SVG -->
        <svg
          class="app-header__mark"
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 64 64"
          width="32"
          height="32"
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
        <span class="app-header__wordmark">QDYN</span>
      </router-link>

      <div class="app-header__actions">
        <!-- Dark mode toggle -->
        <el-button
          text
          circle
          class="app-header__theme-toggle"
          @click="themeStore.toggle()"
          :aria-label="themeStore.isDark ? 'Switch to light mode' : 'Switch to dark mode'"
        >
          <el-icon :size="18">
            <Moon v-if="!themeStore.isDark" />
            <Sunny v-else />
          </el-icon>
        </el-button>

        <!-- Username display -->
        <span class="app-header__username">{{ authStore.username }}</span>

        <!-- Logout button -->
        <el-button type="danger" text @click="handleLogout">
          Logout
        </el-button>
      </div>
    </div>
  </header>
</template>

<script setup lang="ts">
import { Moon, Sunny } from '@element-plus/icons-vue'
import { useThemeStore } from '@/stores/theme'
import { useAuthStore } from '@/stores/auth'

const themeStore = useThemeStore()
const authStore = useAuthStore()

function handleLogout(): void {
  authStore.logout()
}
</script>

<style scoped>
.app-header {
  position: sticky;
  top: 0;
  z-index: 100;
  height: 64px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-subtle);
}

.app-header__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 1200px;
  height: 100%;
  margin: 0 auto;
  padding: 0 24px;
}

.app-header__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
  color: var(--fg-primary);
}

.app-header__mark {
  color: var(--brand-primary);
  flex-shrink: 0;
}

.app-header__wordmark {
  font-weight: 600;
  font-size: 18px;
  letter-spacing: 2px;
  color: var(--fg-primary);
}

.app-header__actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.app-header__theme-toggle {
  color: var(--fg-secondary);
}

.app-header__theme-toggle:hover {
  color: var(--brand-primary);
}

.app-header__username {
  font: var(--text-body-strong);
  color: var(--fg-secondary);
}
</style>
