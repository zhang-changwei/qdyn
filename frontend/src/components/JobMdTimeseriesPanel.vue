<template>
  <div class="md-timeseries-panel">
    <!-- Loading -->
    <div v-if="loading" class="ts-loading">
      <el-skeleton :rows="6" animated />
    </div>

    <!-- Error -->
    <div v-else-if="errorMsg" class="ts-error">
      <el-alert :title="errorMsg" type="warning" :closable="false" show-icon />
    </div>

    <!-- Empty / not available -->
    <div v-else-if="!data || !data.available || !data.series" class="ts-empty">
      <el-empty
        :description="data?.warning || 'No MD timeseries data available'"
        :image-size="60"
      />
    </div>

    <!-- Chart -->
    <div v-else class="ts-chart-container">
      <!-- Header with attempt selector and stats -->
      <div class="ts-header">
        <div class="ts-header-left">
          <el-text size="small" type="info">MD Timeseries</el-text>
          <el-select
            v-if="data.attempts.length > 1"
            v-model="selectedAttempt"
            size="small"
            style="width: 180px; margin-left: 12px;"
            @change="handleAttemptChange"
          >
            <el-option
              v-for="att in data.attempts"
              :key="att.attempt"
              :label="att.label"
              :value="att.attempt"
            />
          </el-select>
        </div>
        <div class="ts-header-right">
          <template v-if="stepType === 'nvt' && data.references?.target_temperature != null">
            <el-tag size="small" type="info">Target {{ data.references.target_temperature }} K</el-tag>
          </template>
          <template v-if="stepType === 'nve' && data.references?.energy_drift_slope_ev_per_step != null">
            <el-tag size="small" type="info">
              Drift {{ data.references.energy_drift_slope_ev_per_step.toExponential(2) }} eV/step
            </el-tag>
          </template>
          <el-text v-if="data.stats" size="small" type="info" style="margin-left: 8px;">
            Step {{ data.stats.current_step }}
            <template v-if="data.stats.total_steps"> / {{ data.stats.total_steps }}</template>
            <template v-if="data.stats.sampled"> (sampled {{ data.stats.returned_points }}/{{ data.stats.original_points }})</template>
          </el-text>
        </div>
      </div>

      <!-- ECharts -->
      <v-chart
        :option="chartOption"
        autoresize
        class="ts-chart"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart, ScatterChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { getJobMdTimeseries } from '@/api/tasks'
import type { JobMdTimeseriesResponse } from '@/api/types'
import type { ComposeOption } from 'echarts/core'
import type { LineSeriesOption, ScatterSeriesOption } from 'echarts/charts'
import type {
  GridComponentOption,
  TooltipComponentOption,
  LegendComponentOption,
  DataZoomComponentOption,
  MarkLineComponentOption,
  MarkAreaComponentOption,
} from 'echarts/components'

// Register ECharts components
use([
  LineChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkLineComponent,
  MarkAreaComponent,
  CanvasRenderer,
])

type ECOption = ComposeOption<
  | LineSeriesOption
  | ScatterSeriesOption
  | GridComponentOption
  | TooltipComponentOption
  | LegendComponentOption
  | DataZoomComponentOption
  | MarkLineComponentOption
  | MarkAreaComponentOption
>

const props = defineProps<{
  taskId: string
  jobUuid: string
  stepType: string | undefined | null
}>()

const loading = ref(false)
const errorMsg = ref<string | null>(null)
const data = ref<JobMdTimeseriesResponse | null>(null)
const selectedAttempt = ref<number | undefined>(undefined)

async function fetchData(attempt?: number): Promise<void> {
  loading.value = true
  errorMsg.value = null
  try {
    const params: { attempt?: number; max_points?: number } = {}
    if (attempt !== undefined) {
      params.attempt = attempt
    }
    data.value = await getJobMdTimeseries(props.taskId, props.jobUuid, params)
    if (data.value?.selected_attempt) {
      selectedAttempt.value = data.value.selected_attempt
    }
  } catch (e) {
    errorMsg.value = e instanceof Error ? e.message : 'Failed to load timeseries data'
    data.value = null
  } finally {
    loading.value = false
  }
}

function handleAttemptChange(val: number): void {
  fetchData(val)
}

onMounted(() => {
  fetchData()
})

// Re-fetch when jobUuid changes (e.g. different row expanded)
watch(() => props.jobUuid, () => {
  selectedAttempt.value = undefined
  fetchData()
})

const chartOption = computed<ECOption>(() => {
  if (!data.value?.series) return {}

  const series = data.value.series
  const refs = data.value.references
  // Prefer API response step_type over parent prop for chart config
  const isNvt = (data.value.step_type ?? props.stepType) === 'nvt'

  // X-axis data
  const xData = series.time_fs

  // Find unconverged point indices
  const unconvergedIndices: number[] = []
  for (let i = 0; i < series.converged.length; i++) {
    if (!series.converged[i]) {
      unconvergedIndices.push(i)
    }
  }

  // ---- Temperature series ----
  const tempSeries: (LineSeriesOption | ScatterSeriesOption)[] = [
    {
      type: 'line',
      name: 'Temperature',
      xAxisIndex: 0,
      yAxisIndex: 0,
      data: xData.map((x, i) => [x, series.temperatures[i]]),
      smooth: false,
      symbol: 'none',
      lineStyle: { width: 1.5 },
      itemStyle: { color: '#E6A23C' },
    },
  ]

  // NVT: target temperature line + tolerance band
  if (isNvt && refs?.target_temperature != null) {
    tempSeries[0] = {
      ...tempSeries[0],
      markLine: {
        silent: true,
        symbol: 'none',
        lineStyle: { type: 'dashed', color: '#F56C6C', width: 1.5 },
        label: { formatter: `TEEND = ${refs.target_temperature} K`, position: 'insideEndTop', fontSize: 11 },
        data: [{ yAxis: refs.target_temperature }],
      } as MarkLineComponentOption,
    } as LineSeriesOption

    if (refs.temperature_tolerance_low != null && refs.temperature_tolerance_high != null) {
      tempSeries[0] = {
        ...tempSeries[0],
        markArea: {
          silent: true,
          itemStyle: { color: 'rgba(245, 108, 108, 0.08)' },
          data: [[
            { yAxis: refs.temperature_tolerance_low },
            { yAxis: refs.temperature_tolerance_high },
          ]],
        } as MarkAreaComponentOption,
      } as LineSeriesOption
    }
  }

  // Unconverged markers on temperature chart
  if (unconvergedIndices.length > 0) {
    tempSeries.push({
      type: 'scatter',
      name: 'SCF Unconverged',
      xAxisIndex: 0,
      yAxisIndex: 0,
      data: unconvergedIndices.map(i => [xData[i], series.temperatures[i]]),
      symbol: 'circle',
      symbolSize: 6,
      itemStyle: { color: '#F56C6C' },
    })
  }

  // ---- Energy series ----
  const energySeries: (LineSeriesOption | ScatterSeriesOption)[] = [
    {
      type: 'line',
      name: 'Total Energy',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: xData.map((x, i) => [x, series.total_energies[i]]),
      smooth: false,
      symbol: 'none',
      lineStyle: { width: 1.5 },
      itemStyle: { color: '#409EFF' },
    },
    {
      type: 'line',
      name: 'Potential Energy',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: xData.map((x, i) => [x, series.potential_energies[i]]),
      smooth: false,
      symbol: 'none',
      lineStyle: { width: 1 },
      itemStyle: { color: '#67C23A' },
    },
    {
      type: 'line',
      name: 'Kinetic Energy',
      xAxisIndex: 1,
      yAxisIndex: 1,
      data: xData.map((x, i) => [x, series.kinetic_energies[i]]),
      smooth: false,
      symbol: 'none',
      lineStyle: { width: 1 },
      itemStyle: { color: '#909399' },
    },
  ]

  // NVE: mean total energy line + drift trend
  if (!isNvt) {
    if (refs?.mean_total_energy != null) {
      energySeries[0] = {
        ...energySeries[0],
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { type: 'dashed', color: '#409EFF', width: 1 },
          label: { formatter: 'Mean E_total', position: 'insideEndTop', fontSize: 11 },
          data: [{ yAxis: refs.mean_total_energy }],
        } as MarkLineComponentOption,
      } as LineSeriesOption
    }

    // Energy drift trend line (as a separate line series)
    if (refs?.energy_drift_slope_ev_per_step != null && refs?.initial_total_energy != null && xData.length >= 2 && series.steps.length >= 2) {
      const slope = refs.energy_drift_slope_ev_per_step
      const intercept = refs.initial_total_energy
      const step0 = series.steps[0]
      // slope is eV/step (real ionic step), so use step numbers directly
      const x0 = xData[0]
      const xEnd = xData[xData.length - 1]
      const y0 = intercept + slope * (series.steps[0] - step0)
      const yEnd = intercept + slope * (series.steps[series.steps.length - 1] - step0)

      energySeries.push({
        type: 'line',
        name: 'Energy Drift',
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: [[x0, y0], [xEnd, yEnd]],
        smooth: false,
        symbol: 'none',
        lineStyle: { width: 1.5, type: 'dashed', color: '#E6A23C' },
        itemStyle: { color: '#E6A23C' },
      })
    }
  }

  // Selected legend items: kinetic energy off by default
  const defaultSelected: Record<string, boolean> = {
    'Kinetic Energy': false,
  }

  const option: ECOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', link: [{ xAxisIndex: 'all' }] },
      formatter: (params: any) => {
        if (!Array.isArray(params) || params.length === 0) return ''
        const firstParam = params[0]
        const step = series.steps[
          series.time_fs.findIndex(t => Math.abs(t - firstParam.value[0]) < 1e-6)
        ]
        let html = `<strong>Step ${step ?? '?'} &nbsp; ${firstParam.value[0].toFixed(1)} fs</strong><br/>`
        for (const p of params) {
          const color = p.color || '#333'
          const val = typeof p.value[1] === 'number' ? p.value[1].toFixed(4) : p.value[1]
          html += `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:4px;"></span>${p.seriesName}: ${val}<br/>`
        }
        return html
      },
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
    },
    legend: {
      data: [
        'Temperature',
        ...(unconvergedIndices.length > 0 ? ['SCF Unconverged'] : []),
        'Total Energy',
        'Potential Energy',
        'Kinetic Energy',
        ...(!isNvt && refs?.energy_drift_slope_ev_per_step != null ? ['Energy Drift'] : []),
      ],
      bottom: 0,
      selected: defaultSelected,
    },
    grid: [
      { left: 70, right: 40, top: 30, height: '30%' },
      { left: 70, right: 40, top: '52%', height: '30%' },
    ],
    xAxis: [
      {
        type: 'value',
        gridIndex: 0,
        axisLabel: { show: false },
        name: '',
        min: xData[0],
        max: xData[xData.length - 1],
      },
      {
        type: 'value',
        gridIndex: 1,
        name: refs?.potim_fs != null ? 'Time (fs)' : 'Step',
        nameLocation: 'center',
        nameGap: 25,
        min: xData[0],
        max: xData[xData.length - 1],
      },
    ],
    yAxis: [
      {
        type: 'value',
        gridIndex: 0,
        name: 'Temperature (K)',
        nameLocation: 'center',
        nameGap: 50,
        scale: true,
        splitLine: { lineStyle: { type: 'dashed' } },
      },
      {
        type: 'value',
        gridIndex: 1,
        name: 'Energy (eV)',
        nameLocation: 'center',
        nameGap: 50,
        scale: true,
        splitLine: { lineStyle: { type: 'dashed' } },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1],
        filterMode: 'none',
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1],
        bottom: 30,
        height: 20,
        filterMode: 'none',
      },
    ],
    series: [...tempSeries, ...energySeries],
  }

  return option
})
</script>

<style scoped>
.md-timeseries-panel {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--el-border-color-lighter);
}

.ts-loading {
  padding: 12px 0;
}

.ts-error {
  padding: 8px 0;
}

.ts-empty {
  padding: 4px 0;
}

.ts-chart-container {
  width: 100%;
}

.ts-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
  flex-wrap: wrap;
  gap: 8px;
}

.ts-header-left {
  display: flex;
  align-items: center;
}

.ts-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ts-chart {
  width: 100%;
  height: 450px;
}
</style>
