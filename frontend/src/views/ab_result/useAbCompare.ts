/**
 * AB对比结果表共享数据层。
 *
 * 导航页（ab_result/index.vue）与详情抽屉（AbCompareDrawer.vue）都从这里取数，
 * 保证两处读取的是同一份业务数据：列表、成员集合指纹、归属范围与口径版本
 * 不会因为两个组件各自请求而出现口径漂移。
 */
import { computed, ref } from 'vue'

import { useSessionStore } from '@/stores/session'

const ENDPOINT = '/api/ab_result/compare'

export type CompareTable = {
  id: number
  结果表编号: string
  实验编号: string
  experiment_id: number
  报告编号: string
  归属范围: string
  口径版本: string
  status: string
  结果类型: string
  重叠处理策略: string
  分群集合: { 分群编号: string; group_type: string; group_id: number; 临时分群?: boolean; 样本基数?: string; access_scope?: string }[]
  分群定义?: Record<string, unknown>[]
  成员集合: { 对照组: string[]; 实验组: string[] }
  成员集合指纹: { 对照组: string; 实验组: string }
  指标结果: {
    指标标识: string
    指标名称: string
    口径版本: string
    对照组均值: number
    实验组均值: number
    差异: number
    效果方向: string
    对照组样本量: number
    实验组样本量: number
  }[]
  待复核清单: { 结果类型: string; 实验编号: string; 重叠用户: string[]; 说明: string }[]
  重叠用户清单: string[]
  越权只读清单: { user_id: string; group_id: number; scope: string; 越权原因: string }[]
  越权成员数: number
  可追溯字段: Record<string, unknown>
  只读?: boolean
}

// 模块级单例状态：导航页和抽屉共享同一份列表数据。
const tables = ref<CompareTable[]>([])
const loading = ref(false)
const errorMessage = ref('')
const strategyMeta = ref<{
  caliber_version: string
  overlap_strategies: string[]
  strategy_labels: Record<string, string>
}>({ caliber_version: 'V010', overlap_strategies: ['target_only', 'isolate'], strategy_labels: {} })

export function useAbCompare() {
  const session = useSessionStore()

  function authHeaders(extra: HeadersInit = {}): HeadersInit {
    return {
      'Content-Type': 'application/json',
      'X-Operator-Scopes': session.scopeHeader,
      ...extra,
    }
  }

  async function loadMeta() {
    try {
      const res = await fetch(`${ENDPOINT}/scopes`)
      if (res.ok) strategyMeta.value = await res.json()
    } catch {
      // 元数据加载失败不阻塞页面，保留默认值
    }
  }

  async function loadTables() {
    loading.value = true
    errorMessage.value = ''
    try {
      const res = await fetch(ENDPOINT, { headers: { 'X-Operator-Scopes': session.scopeHeader } })
      const data = await res.json()
      tables.value = data.items ?? []
    } catch (error) {
      errorMessage.value = error instanceof Error ? error.message : 'AB对比结果表读取失败'
    } finally {
      loading.value = false
    }
  }

  async function generateTable(payload: {
    experiment_id: number
    overlap_strategy: string
    simulate_interrupt?: boolean
  }) {
    const res = await fetch(ENDPOINT, {
      method: 'POST',
      headers: authHeaders(),
      body: JSON.stringify(payload),
    })
    const data = await res.json()
    if (!res.ok || data.ok === false) {
      throw new Error(data.message || '生成失败')
    }
    await loadTables()
    return data.entry as CompareTable
  }

  async function archiveTable(id: number) {
    const res = await fetch(`${ENDPOINT}/${id}/archive`, {
      method: 'POST',
      headers: authHeaders(),
    })
    return res.json()
  }

  async function handoverTable(id: number) {
    const res = await fetch(`${ENDPOINT}/${id}/handover`, {
      method: 'POST',
      headers: authHeaders(),
    })
    return res.json()
  }

  async function caliberCheck(id: number) {
    const res = await fetch(`${ENDPOINT}/${id}/caliber_check`, {
      headers: { 'X-Operator-Scopes': session.scopeHeader },
    })
    return res.json()
  }

  async function loadEligibleExperiments() {
    const res = await fetch(`${ENDPOINT}/eligible_experiments`)
    if (!res.ok) throw new Error('可对比实验读取失败')
    return res.json() as Promise<{
      items: { id: number; 方案编号: string; 实验名称: string; access_scope: string }[]
      total: number
    }>
  }

  async function loadGroupMembers(resultId: number, groupId: number) {
    const res = await fetch(`${ENDPOINT}/${resultId}/groups/${groupId}/members`, {
      headers: { 'X-Operator-Scopes': session.scopeHeader },
    })
    if (!res.ok) throw new Error('分群成员明细读取失败')
    return res.json()
  }

  const total = computed(() => tables.value.length)

  return {
    tables,
    loading,
    errorMessage,
    strategyMeta,
    total,
    loadMeta,
    loadTables,
    loadEligibleExperiments,
    generateTable,
    archiveTable,
    handoverTable,
    caliberCheck,
    loadGroupMembers,
  }
}
