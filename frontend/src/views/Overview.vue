<template>
  <section class="page">
    <header class="page-head">
      <div>
        <h2>运营概览</h2>
        <p class="page-desc">汇总各业务模块的关键指标，先看总量再看异常。</p>
      </div>
    </header>
    <div class="stat-row">
      <article v-for="card in cards" :key="card.label" class="stat-card">
        <span class="stat-label">{{ card.label }}</span>
        <strong class="stat-value">{{ card.value }}</strong>
      </article>
    </div>
    <table class="data-table">
      <thead>
        <tr><th>业务模块</th><th>今日新增</th><th>待处理</th><th>异常量</th></tr>
      </thead>
      <tbody>
        <tr v-for="row in moduleRows" :key="row.name">
          <td>{{ row.name }}</td>
          <td>{{ row.created }}</td>
          <td>{{ row.pending }}</td>
          <td>{{ row.abnormal }}</td>
        </tr>
      </tbody>
    </table>

    <!-- AB对比结果表摘要：与AB结果分析页/详情抽屉共用 useAbCompare 同一份业务数据 -->
    <section class="compare-summary" data-testid="overview-compare">
      <header class="page-head">
        <div>
          <h3>AB对比结果表（{{ strategyMeta.caliber_version }}）</h3>
          <p class="page-desc">导航页与详情抽屉读取同一业务数据，按当前归属范围展示。</p>
        </div>
        <RouterLink class="btn" to="/ab_result">前往AB结果分析</RouterLink>
      </header>
      <div class="stat-row">
        <article class="stat-card"><span class="stat-label">结果表总数</span><strong class="stat-value">{{ compareTotal }}</strong></article>
        <article class="stat-card"><span class="stat-label">含越权只读成员的表</span><strong class="stat-value">{{ tablesWithUnauthorized }}</strong></article>
        <article class="stat-card"><span class="stat-label">已V010归档</span><strong class="stat-value">{{ archivedCount }}</strong></article>
        <article class="stat-card"><span class="stat-label">已转交（只读）</span><strong class="stat-value">{{ handedOverCount }}</strong></article>
      </div>
      <table class="data-table" v-if="tables.length">
        <thead><tr><th>结果表编号</th><th>实验编号</th><th>归属范围</th><th>越权只读</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="t in tables" :key="t.id" data-testid="overview-compare-row">
            <td>{{ t.结果表编号 }}</td><td>{{ t.实验编号 }}</td><td>{{ t.归属范围 }}</td>
            <td>{{ t.越权成员数 }}</td><td>{{ t.status }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else class="empty-state" style="padding:12px">当前归属范围下暂无AB对比结果表</p>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { fetchJson } from '@/api/client'
import { useAbCompare } from '@/views/ab_result/useAbCompare'

type Overview = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

const cards = ref<Overview['cards']>([])
const moduleRows = ref<Overview['modules']>([])

// 与AB结果分析页、详情抽屉共用同一个模块级单例状态，保证读取同一业务数据。
const { tables, total: compareTotal, strategyMeta, loadMeta, loadTables } = useAbCompare()
const tablesWithUnauthorized = computed(() => tables.value.filter((t) => t.越权成员数 > 0).length)
const archivedCount = computed(() => tables.value.filter((t) => t.status === '已归档').length)
const handedOverCount = computed(() => tables.value.filter((t) => t.status === '已转交').length)

onMounted(async () => {
  try {
    const payload = await fetchJson<Overview>('/api/overview')
    cards.value = payload.cards
    moduleRows.value = payload.modules
  } catch {
    cards.value = [{"label": "业务模块", "value": 0}, {"label": "今日新增", "value": 0}]
    moduleRows.value = [{"name": "实验设计", "created": 0, "pending": 0, "abnormal": 0}, {"name": "样本分群", "created": 0, "pending": 0, "abnormal": 0}, {"name": "指标定义", "created": 0, "pending": 0, "abnormal": 0}, {"name": "AB结果分析", "created": 0, "pending": 0, "abnormal": 0}, {"name": "分群对比", "created": 0, "pending": 0, "abnormal": 0}, {"name": "多维下钻", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据筛选", "created": 0, "pending": 0, "abnormal": 0}, {"name": "归因分析", "created": 0, "pending": 0, "abnormal": 0}, {"name": "异常检测", "created": 0, "pending": 0, "abnormal": 0}, {"name": "预测模型", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据导出", "created": 0, "pending": 0, "abnormal": 0}, {"name": "同期群追踪", "created": 0, "pending": 0, "abnormal": 0}, {"name": "可视化配置", "created": 0, "pending": 0, "abnormal": 0}, {"name": "洞察报告", "created": 0, "pending": 0, "abnormal": 0}, {"name": "数据新鲜度", "created": 0, "pending": 0, "abnormal": 0}, {"name": "口径注册", "created": 0, "pending": 0, "abnormal": 0}, {"name": "实验因子", "created": 0, "pending": 0, "abnormal": 0}, {"name": "评估看板", "created": 0, "pending": 0, "abnormal": 0}]
  }
  await loadMeta()
  await loadTables()
})
</script>

<style scoped>
.compare-summary { margin-top: 24px; background: #fff; border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
</style>
