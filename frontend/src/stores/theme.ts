import { defineStore } from 'pinia'
import { ref, watchEffect } from 'vue'

const STORAGE_KEY = 'qdyn-theme'

export const useThemeStore = defineStore('theme', () => {
  const isDark = ref(localStorage.getItem(STORAGE_KEY) === 'dark')

  watchEffect(() => {
    const html = document.documentElement
    html.classList.toggle('dark', isDark.value)
    html.dataset.theme = isDark.value ? 'dark' : 'light'
    localStorage.setItem(STORAGE_KEY, isDark.value ? 'dark' : 'light')
  })

  function toggle() {
    isDark.value = !isDark.value
  }

  return { isDark, toggle }
})
