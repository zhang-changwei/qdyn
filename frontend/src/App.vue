<template>
  <AppHeader v-if="route.meta.requiresAuth" />
  <router-view />
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import AppHeader from '@/components/AppHeader.vue'

const route = useRoute()
</script>

<style>
html,
body {
  height: 100%;
  margin: 0;
  padding: 0;
  background: var(--bg-page);
}

#app {
  height: 100%;
  margin: 0;
  padding: 0;
}
</style>
