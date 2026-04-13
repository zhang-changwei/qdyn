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
import { WEAS, Atoms } from 'weas'
import { Color } from 'three'
import 'weas/style.css'
import type { StructurePreviewPayload } from '@/api/types'

const props = withDefaults(defineProps<{
  preview: StructurePreviewPayload | null
  height?: string
}>(), {
  height: '400px'
})

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
  border-radius: 8px;
  overflow: hidden;
  background-color: #f5f5f5;
}

.structure-viewer {
  width: 100%;
  height: 100%;
}

.constraint-legend {
  position: absolute;
  bottom: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: rgba(255, 255, 255, 0.85);
  border-radius: 4px;
  font-size: 12px;
  color: #555;
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
  border: 1px solid #666;
}
</style>
