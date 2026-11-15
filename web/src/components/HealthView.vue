<!-- ============================================================================
 * HealthView.vue — 平台健康灯阵页（PR-4 真实视图；原 poc-health.html 演示转正）
 *
 * 接 GET /health（免鉴权探针路径，经 vite 代理），用 src/api/health.ts 的
 * HEALTH_LAMP_GROUPS（5 组 30 字段）/ HEALTH_LAMP_WHY（字段→判读说明）渲染灯阵。
 * 形状四档：true 实心圆 / false 空心圆 / null 实心警示圆 / 非布尔 方块（如实显示）。
 * false 与 null 必须是不同形状，否则「接线 ≠ 启用」被抹平（视觉件 §2.1）。
 * ⚠ 本件无 <style> 块（工程约束）；灯阵类全在 events.css。
 * ==========================================================================-->
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { HEALTH_LAMP_GROUPS, HEALTH_LAMP_WHY, getHealth } from '../api/health.ts'

type Shape = 'on' | 'off' | 'null' | 'muted'

function shapeOf(v: unknown): Shape {
  if (v === true) return 'on'
  if (v === false) return 'off'
  if (v === null) return 'null'
  return 'muted'
}

function displayVal(v: unknown): string {
  if (v === null) return 'null'
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}

const data = ref<Record<string, unknown> | null>(null)
const errorText = ref('')
const busy = ref(false)
const fetchedAt = ref('')

async function refresh(): Promise<void> {
  errorText.value = ''
  busy.value = true
  try {
    const res = await getHealth()
    data.value = res
    fetchedAt.value = new Date().toLocaleTimeString()
  } catch (err) {
    errorText.value = err instanceof Error ? err.message : String(err)
    data.value = null
  } finally {
    busy.value = false
  }
}

onMounted(() => { void refresh() })

const groups = Object.entries(HEALTH_LAMP_GROUPS)
</script>

<template>
  <div class="col">
    <section
      class="ry-card"
      aria-labelledby="hHealth"
    >
      <h2 id="hHealth">
        平台健康
        <span class="count-badge">{{ data ? Object.keys(data).length : 0 }}</span>
      </h2>
      <p class="hint">
        灯阵直读 <code class="t-name">/health</code> 真实状态（免鉴权探针路径）。每盏灯的形状就是判读：
        实心圆 = 已启用（true），空心圆 = 未启用（false），实心警示圆 = 未装配（null），方块 = 非布尔值（如实显示）。
      </p>

      <div class="composer__row">
        <button
          type="button"
          class="ry-btn ry-btn--primary"
          :aria-disabled="busy"
          @click="refresh"
        >
          {{ busy ? '刷新中…' : '刷新' }}
        </button>
        <span
          v-if="fetchedAt"
          class="hint"
        >最近拉取：{{ fetchedAt }}</span>
      </div>

      <p
        v-if="errorText"
        class="banner"
      >
        <strong>{{ errorText }}</strong>
      </p>

      <!-- 四档形状判读面板：形状是「接线 ≠ 启用」的唯一区分通道，须与灯同屏 -->
      <div class="shapekey">
        <div class="sk-row">
          <span class="dot dot--on" /> 已启用（true）
        </div>
        <div class="sk-row">
          <span class="dot dot--off" /> 未启用（false）
        </div>
        <div class="sk-row">
          <span class="dot dot--null" /> 未装配（null）
        </div>
        <div class="sk-row">
          <span class="dot dot--muted" /> 非布尔值（如实显示）
        </div>
      </div>
    </section>

    <template v-if="data">
      <section
        v-for="[group, keys] in groups"
        :key="group"
        class="ry-card lamp-group"
        aria-labelledby="hG"
      >
        <h3 class="o-head-sm">
          {{ group }}
        </h3>
        <div class="lamps">
          <div
            v-for="key in keys"
            :key="key"
            class="lamp"
          >
            <div class="lamp__head">
              <span :class="['dot', `dot--${shapeOf(data[key])}`]" />
              <span class="lamp__key">{{ key }}</span>
            </div>
            <div class="lamp__val">
              {{ displayVal(data[key]) }}
            </div>
            <div class="lamp__why">
              {{ HEALTH_LAMP_WHY[key] ?? '' }}
            </div>
          </div>
        </div>
      </section>
    </template>

    <p
      v-else-if="!errorText"
      class="hint"
    >
      尚未加载（点「刷新」拉取 GET /health）。
    </p>
  </div>
</template>
