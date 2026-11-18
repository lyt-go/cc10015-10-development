<template>
  <section class="page" data-module="ab_result">
    <header class="page-head">
      <div><h2>AB结果分析</h2><p class="page-desc">维护分析报告的输入、执行约束与结果记录，为AB结果分析提供可验证的数据工程流程。</p></div>
    </header>
    <div class="analysis-summary">
      <article v-for="m in summaryMetrics" :key="m.label" class="analysis-card" data-testid="kpi-card">
        <span style="font-size:12px;color:var(--muted)">{{ m.label }}</span>
        <strong style="font-size:22px;display:block">{{ m.value }}</strong>
        <span :class="m.trend > 0 ? 'trend-up' : 'trend-down'" style="font-size:12px">{{ m.trend > 0 ? '↑' : '↓' }}{{ Math.abs(m.trend) }}%</span>
      </article>
    </div>
    <form class="analysis-form" @submit.prevent="runAnalysis">
      <label v-for="field in paramFields" :key="field"><span>{{ field }}</span>
        <select v-if="field.includes('方法')||field.includes('策略')||field.includes('粒度')" v-model="params[field]"><option v-for="o in options[field]" :key="o" :value="o">{{ o }}</option></select>
        <input v-else v-model="params[field]" :placeholder="`请输入${field}`" />
      </label>
      <button class="btn primary" type="submit" data-testid="run-analysis">运行分析</button>
    </form>
    <div v-if="chartData.length" class="analysis-chart">
      <div v-for="(bar, i) in chartData" :key="i" class="analysis-bar" :style="{ height: barHeight(bar.value) + 'px' }"><span>{{ bar.label }}</span></div>
    </div>
    <table class="data-table" v-if="results.length">
      <thead><tr><th v-for="c in resultColumns" :key="c">{{ c }}</th></tr></thead>
      <tbody><tr v-for="row in results" :key="row.id"><td v-for="c in resultColumns" :key="c">{{ row[c] ?? '—' }}</td></tr></tbody>
    </table>
    <p v-if="!results.length && !loading" style="text-align:center;color:var(--muted)">请配置参数后运行分析</p>

    <!-- AB对比结果表：按实验归属生成，每行差异只来自同一实验的对照与样本组 -->
    <section class="compare-block" data-testid="compare-block">
      <header class="page-head">
        <div>
          <h3>AB对比结果表（{{ strategyMeta.caliber_version }}）</h3>
          <p class="page-desc">读取分析报告与分群成员明细，按实验归属过滤后用同一成员集合计算差异；越权成员只读、不入正式差异。</p>
        </div>
      </header>

      <div class="scope-bar">
        <label><span>当前归属范围</span>
          <select v-model="scopeSelection" data-testid="scope-select" @change="onScopeChange">
            <option value="__all__">平台管理员（全部范围）</option>
            <option value="scope-a">scope-a</option>
            <option value="scope-b">scope-b</option>
          </select>
        </label>
        <label><span>目标实验</span>
          <select v-model.number="selectedExperimentId" data-testid="experiment-select">
            <option v-for="exp in experiments" :key="exp.id" :value="exp.id">
              {{ exp.方案编号 }} · {{ exp.实验名称 }}（{{ exp.access_scope }}）
            </option>
          </select>
        </label>
        <label><span>版本冲突策略</span>
          <select v-model="overlapStrategy" data-testid="strategy-select">
            <option v-for="s in strategyMeta.overlap_strategies" :key="s" :value="s">
              {{ strategyMeta.strategy_labels[s] || s }}
            </option>
          </select>
        </label>
        <button class="btn primary" type="button" data-testid="generate-compare" :disabled="compareBusy" @click="onGenerate">
          {{ compareBusy ? '生成中…' : '生成对比结果表' }}
        </button>
        <button class="btn" type="button" data-testid="simulate-interrupt" @click="onInterrupt">模拟重算中断（沿用上一版）</button>
        <button class="btn ghost" type="button" data-testid="refresh-compare" @click="loadTables">刷新</button>
      </div>
      <p v-if="compareMessage" class="error-text" data-testid="compare-message">{{ compareMessage }}</p>

      <table class="data-table" v-if="tables.length">
        <thead>
          <tr>
            <th>结果表编号</th><th>实验编号</th><th>报告编号</th><th>归属范围</th>
            <th>指标标识</th><th>对照组/实验组样本量</th><th>差异</th><th>重叠用户</th>
            <th>越权只读</th><th>权限</th><th>状态</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in tables" :key="t.id" data-testid="compare-row" :data-status="t.status" :data-readonly="String(!!t.只读)">
            <td>{{ t.结果表编号 }}</td>
            <td>{{ t.实验编号 }}</td>
            <td>{{ t.报告编号 }}</td>
            <td data-testid="row-scope">{{ t.归属范围 }}</td>
            <td>{{ t.指标结果.map((r) => r.指标标识).join('、') }}</td>
            <td>{{ t.指标结果[0]?.对照组样本量 }} / {{ t.指标结果[0]?.实验组样本量 }}</td>
            <td :class="(t.指标结果[0]?.差异 ?? 0) > 0 ? 'trend-up' : 'trend-down'">{{ t.指标结果[0]?.差异 }}</td>
            <td>{{ t.重叠用户清单.length }}</td>
            <td data-testid="row-unauthorized-count">{{ t.越权成员数 }}</td>
            <td data-testid="row-access">{{ t.只读 ? '只读' : '可操作' }}</td>
            <td>{{ t.status }}</td>
            <td class="row-actions">
              <button class="link" type="button" data-testid="open-drawer" @click="openDrawer(t)">查看抽屉</button>
            </td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state" style="padding:16px">当前归属范围下暂无AB对比结果表，请先生成</p>
    </section>

    <AbCompareDrawer v-if="activeTable" :table="activeTable" @close="activeTable = null" @changed="onDrawerChanged" />
  </section>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { request } from '@/api/client'
import { useSessionStore } from '@/stores/session'
import AbCompareDrawer from './AbCompareDrawer.vue'
import { useAbCompare, type CompareTable } from './useAbCompare'

const ENDPOINT = '/api/ab_result'
const session = useSessionStore()
const { tables, strategyMeta, loadMeta, loadTables, loadEligibleExperiments, generateTable } = useAbCompare()

const summaryMetrics = ref<{label:string;value:number;trend:number}[]>([])
const results = ref<any[]>([]); const chartData = ref<{label:string;value:number}[]>([])
const loading = ref(false)
const params = ref<Record<string,string>>({})
const paramFields = ["报告编号", "实验编号", "分析指标", "对照组均值", "实验组均值", "置信水平", "效果方向", "生成时间"].filter((f: string) => !['编号','名称','版本'].includes(f)).slice(0, 4)
const options: Record<string,string[]> = { '统计粒度': ['按日','按周','按月'], '分组字段': ['全量','按类型','按区域'], '比较方法': ['环比','同比','绝对值'], '时间范围': ['最近7天','最近30天','最近90天'] }
const resultColumns = ref(["报告编号", "实验编号", "分析指标", "对照组均值", "实验组均值", "置信水平", "效果方向", "生成时间"].slice(0, 5))

const experiments = ref<Record<string, any>[]>([])
const selectedExperimentId = ref<number | null>(null)
const overlapStrategy = ref('target_only')
const scopeSelection = ref('__all__')
const compareBusy = ref(false)
const compareMessage = ref('')
const activeTable = ref<CompareTable | null>(null)

function barHeight(v: number) { const max = Math.max(...chartData.value.map(d => d.value), 1); return Math.max(10, (v / max) * 140) }
async function fetchSummary() { try { const res = await request(`${ENDPOINT}/summary`); summaryMetrics.value = (await res.json()).metrics || [] } catch(e) {} }
async function runAnalysis() {
  loading.value = true
  try { const res = await request(`${ENDPOINT}/run`, { method: 'POST', body: JSON.stringify({ values: params.value }) }); const data = await res.json(); results.value = data.items || []; chartData.value = (data.items || []).map((r: any) => ({ label: Object.values(r)[0] as string, value: Object.values(r).filter(v => typeof v === 'number')[0] as number || 0 })).slice(0, 6) } catch(e) { results.value = [] }
  loading.value = false
}

async function loadExperiments() {
  // 只列出带可读分析报告、可生成对比结果表的实验，与抽屉读取同一业务数据。
  try {
    const data = await loadEligibleExperiments()
    experiments.value = data.items ?? []
    if (experiments.value.length && selectedExperimentId.value === null) {
      selectedExperimentId.value = Number(experiments.value[0].id)
    }
  } catch {
    experiments.value = []
  }
}

function onScopeChange() {
  session.setOperatorScopes(scopeSelection.value === '__all__' ? [] : [scopeSelection.value])
  compareMessage.value = ''
  loadTables()
}

async function onGenerate() {
  if (!selectedExperimentId.value) return
  compareBusy.value = true
  compareMessage.value = ''
  try {
    const entry = await generateTable({
      experiment_id: selectedExperimentId.value,
      overlap_strategy: overlapStrategy.value,
    })
    compareMessage.value = `已生成 ${entry.结果表编号}：正式差异仅含实验 ${entry.实验编号} 的授权成员，越权成员 ${entry.越权成员数} 人只读`
  } catch (error) {
    compareMessage.value = error instanceof Error ? error.message : '生成失败'
  } finally {
    compareBusy.value = false
  }
}

async function onInterrupt() {
  if (!selectedExperimentId.value) return
  compareBusy.value = true
  compareMessage.value = ''
  try {
    const entry = await generateTable({
      experiment_id: selectedExperimentId.value,
      overlap_strategy: overlapStrategy.value,
      simulate_interrupt: true,
    })
    compareMessage.value = `重算中断，已沿用上一版完整结果 ${entry.结果表编号}（状态：${entry.status}），未用越权成员补齐`
  } catch (error) {
    compareMessage.value = error instanceof Error ? error.message : '中断处理失败'
  } finally {
    compareBusy.value = false
  }
}

function openDrawer(table: CompareTable) {
  activeTable.value = table
}

async function onDrawerChanged() {
  await loadTables()
  const updated = tables.value.find((t) => t.id === activeTable.value?.id)
  if (updated) activeTable.value = updated
}

onMounted(async () => {
  await fetchSummary()
  await loadMeta()
  await loadExperiments()
  await loadTables()
})
</script>
<style scoped>
.compare-block { margin-top: 24px; background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.scope-bar { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; margin-bottom: 12px; }
.scope-bar label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: var(--muted); }
.scope-bar select { padding: 6px 10px; border: 1px solid var(--border); border-radius: 6px; min-width: 180px; }
.trend-up { color: #16a34a; font-weight: 600; }
.trend-down { color: #dc2626; font-weight: 600; }
</style>
