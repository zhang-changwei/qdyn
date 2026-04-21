/// <reference types="vite/client" />
/// <reference types="@types/three" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}

// Three.js type definitions are provided by @types/three (v0.183.1).
// No manual stubs needed -- @types/three covers the full API.

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
