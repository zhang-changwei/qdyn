<template>
  <div class="structure-viewer-wrapper" :style="{ height }">
    <div ref="containerRef" class="structure-viewer" />
    <div v-if="hasConstraints" class="constraint-legend">
      <span class="legend-swatch constrained" />
      <span>Fixed atoms</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { storeToRefs } from 'pinia'
import { WEAS, Atoms } from 'weas'
import { Color } from 'three'
import 'weas/style.css'
import { useThemeStore } from '@/stores/theme'
import type { StructurePreviewPayload } from '@/api/types'

const props = withDefaults(defineProps<{
  preview: StructurePreviewPayload | null
  height?: string
}>(), {
  height: '400px'
})

const themeStore = useThemeStore()
const { isDark } = storeToRefs(themeStore)

const containerRef = ref<HTMLElement | null>(null)
let viewer: InstanceType<typeof WEAS> | null = null

// Cold-tinted gray target for constrained (fixed) atoms
const CONSTRAINT_GRAY = new Color(0x7a8794)
const CONSTRAINT_LERP = 0.7

/** Whether the current preview contains any constrained atoms. */
const hasConstraints = computed(() => {
  const mask = props.preview?.constraint_mask
  return Array.isArray(mask) && mask.some(Boolean)
})

/**
 * Convert backend StructurePreviewPayload to WEAS Atoms object.
 */
function previewToAtoms(preview: StructurePreviewPayload): InstanceType<typeof Atoms> {
  return new Atoms({
    symbols: preview.species,
    positions: preview.cart_coords as [number, number, number][],
    cell: preview.lattice as [number, number, number][],
    pbc: preview.pbc,
  })
}

/**
 * Post-render color patch: desaturate constrained atoms toward gray.
 *
 * Reads original element colors from viewer.avr.atomColors (reset on every
 * drawBalls), so the operation is idempotent — safe to call multiple times
 * on the same mesh without cumulative darkening.
 */
function applyConstraintVisualization(): void {
  if (!viewer || !props.preview?.constraint_mask) return

  const mask = props.preview.constraint_mask
  const avr = viewer.avr as any
  const atomMesh = avr?.atomManager?.meshes?.['atom']
  const atomColors: Color[] | undefined = avr?.atomColors
  if (!atomMesh || !atomColors) return

  const limit = Math.min(mask.length, atomColors.length)
  let patched = false

  for (let i = 0; i < limit; i++) {
    if (mask[i]) {
      const c = atomColors[i].clone().lerp(CONSTRAINT_GRAY, CONSTRAINT_LERP)
      atomMesh.setColorAt(i, c)
      patched = true
    }
  }

  if (patched && atomMesh.instanceColor) {
    atomMesh.instanceColor.needsUpdate = true
  }

  // Sync image atoms (boundary / bonded) if present
  const imageMesh = avr?.atomManager?.meshes?.['image']
  const imageAtomsList: [number, number[]][] | undefined = avr?.imageAtomsList
  if (imageMesh && imageAtomsList) {
    let imagePatched = false
    imageAtomsList.forEach(([srcIdx]: [number, ...unknown[]], imgIdx: number) => {
      if (srcIdx < limit && mask[srcIdx]) {
        const c = atomColors[srcIdx].clone().lerp(CONSTRAINT_GRAY, CONSTRAINT_LERP)
        imageMesh.setColorAt(imgIdx, c)
        imagePatched = true
      }
    })
    if (imagePatched && imageMesh.instanceColor) {
      imageMesh.instanceColor.needsUpdate = true
    }
  }

  if (patched) {
    viewer.render()
  }
}

/**
 * Update the Three.js scene background to match the current theme.
 */
function applyViewerBackground(): void {
  if (!viewer) return
  const bgHex = isDark.value ? 0x161b25 : 0xf4f5f8
  try {
    const scene = viewer.tjs.scene
    if (scene) {
      scene.background = new Color(bgHex)
      viewer.render()
    }
  } catch {
    // Viewer may not be fully initialized yet
  }
}

// React to theme changes
watch(isDark, () => {
  applyViewerBackground()
})

function initViewer(): void {
  if (!containerRef.value) return

  // Dispose previous if exists
  disposeViewer()

  const atoms = props.preview ? [previewToAtoms(props.preview)] : []

  viewer = new WEAS({
    domElement: containerRef.value,
    atoms,
    viewerConfig: {
      modelStyle: 1, // ball-and-stick
    },
    guiConfig: {
      buttons: {
        import: false, // hide upload button (we have our own uploader)
      },
    },
  })

  viewer.avr.modelStyle = 1
  viewer.render()
  applyConstraintVisualization()
  applyViewerBackground()
}


function disposeViewer(): void {
  if (viewer) {
    try {
      // Dispose tooltip (not disposed in AtomsViewer.dispose() to survive redraws)
      viewer.avr?.tooltipManager?.dispose?.()
      viewer.tjs.dispose?.()
    } catch {
      // ignore cleanup errors
    }
    viewer = null
  }
  if (containerRef.value) {
    containerRef.value.innerHTML = ''
  }
}

onMounted(() => {
  nextTick(() => initViewer())
})

watch(
  () => props.preview,
  (newPreview) => {
    if (!newPreview) return
    initViewer()
  },
)

onUnmounted(() => {
  disposeViewer()
})
</script>

<style scoped>
.structure-viewer-wrapper {
  position: relative;
  width: 100%;
  border-radius: var(--radius-lg);
  overflow: hidden;
  background-color: var(--bg-page);
}

.structure-viewer {
  width: 100%;
  height: 100%;
}

.constraint-legend {
  position: absolute;
  bottom: var(--space-2);
  right: var(--space-2);
  display: flex;
  align-items: center;
  gap: var(--space-1);
  padding: 2px var(--space-2);
  background: var(--bg-surface);
  opacity: 0.88;
  border-radius: var(--radius-sm);
  font-size: var(--fs-12);
  color: var(--fg-secondary);
  pointer-events: none;
  z-index: 10;
}

.legend-swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
}

.legend-swatch.constrained {
  background: #7a8794;
  border: 1px solid var(--ink-400);
}
</style>
