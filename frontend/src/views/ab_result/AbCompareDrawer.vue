<template>
  <div v-if="table" class="drawer-backdrop" data-testid="compare-drawer" @click.self="emit('close')">
    <aside class="drawer">
      <header class="drawer-head">
        <div>
          <h3>{{ table.结果表编号 }} · {{ table.实验编号 }}</h3>
          <p class="page-desc">AB对比结果表 {{ table.口径版本 }} 留档核对视图，共享内容只读</p>
        </div>
        <button class="btn" type="button" data-testid="drawer-close" @click="emit('close')">关闭</button>
      </header>

      <div class="drawer-body">
        <section class="drawer-section">
          <h4>归属与追溯</h4>
          <dl class="drawer-grid">
            <dt>归属范围</dt><dd data-testid="drawer-scope">{{ table.归属范围 }}</dd>
            <dt>报告编号</dt><dd>{{ table.报告编号 }}</dd>
            <dt>结果类型</dt><dd>{{ table.结果类型 }}</dd>
            <dt>表状态</dt><dd data-testid="drawer-status">{{ table.status }}</dd>
            <dt>重叠策略</dt><dd>{{ strategyLabel(table.重叠处理策略) }}</dd>
            <dt>口径版本</dt><dd>{{ table.口径版本 }}</dd>
            <dt>当前权限</dt><dd data-testid="drawer-access">
              <span :class="table.只读 ? 'badge-readonly' : 'badge-writable'">{{ table.只读 ? '只读（共享内容不可改动）' : '可操作' }}</span>
            </dd>
          </dl>
        </section>

        <section class="drawer-section">
          <h4>指标差异（同一实验对照 vs 实验，同一授权成员集合）</h4>
          <table class="data-table">
            <thead>
              <tr>
                <th>指标标识</th><th>指标名称</th><th>对照组均值</th><th>实验组均值</th>
                <th>差异</th><th>效果方向</th><th>对照组样本量</th><th>实验组样本量</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in table.指标结果" :key="row.指标标识" data-testid="drawer-metric-row">
                <td>{{ row.指标标识 }}</td><td>{{ row.指标名称 }}</td>
                <td>{{ row.对照组均值 }}</td><td>{{ row.实验组均值 }}</td>
                <td :class="row.差异 > 0 ? 'trend-up' : 'trend-down'">{{ row.差异 }}</td>
                <td>{{ row.效果方向 }}</td>
                <td>{{ row.对照组样本量 }}</td><td>{{ row.实验组样本量 }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <section class="drawer-section">
          <h4>成员集合指纹（实验归属过滤与差异计算同源）</h4>
          <dl class="drawer-grid">
            <dt>对照组指纹</dt><dd data-testid="drawer-fingerprint-control">{{ table.成员集合指纹.对照组 }}</dd>
            <dt>实验组指纹</dt><dd data-testid="drawer-fingerprint-experiment">{{ table.成员集合指纹.实验组 }}</dd>
            <dt>对照组人数</dt><dd>{{ table.成员集合.对照组.length }}</dd>
            <dt>实验组人数</dt><dd>{{ table.成员集合.实验组.length }}</dd>
          </dl>
          <button class="btn" type="button" data-testid="load-members" @click="toggleMembers">
            {{ showMembers ? '收起分群成员明细' : '读取分群成员明细' }}
          </button>
          <table v-if="showMembers" class="data-table member-table">
            <thead>
              <tr><th>user_id</th><th>分群</th><th>归属实验</th><th>范围</th><th>重叠</th><th>指标值</th></tr>
            </thead>
            <tbody>
              <tr v-for="m in memberPreview" :key="`${m.group_id}-${m.user_id}`"
                  :data-testid="`member-${m.user_id}`" :data-unauthorized="String(isUnauthorized(m))">
                <td>{{ m.user_id }}</td><td>{{ m.group_id }}</td>
                <td>{{ m.experiment_id }}</td><td>{{ m.scope }}</td>
                <td>{{ m.is_overlap ? '是' : '否' }}</td><td>{{ m.metric_value }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="memberNote" class="page-desc">{{ memberNote }}</p>
        </section>

        <section class="drawer-section">
          <h4>越权只读清单（{{ table.越权成员数 }} 人，不进入正式差异）</h4>
          <ul v-if="table.越权只读清单.length" class="review-list">
            <li v-for="m in table.越权只读清单" :key="`${m.group_id}-${m.user_id}`" data-testid="drawer-unauthorized">
              {{ m.user_id }} · {{ m.scope }} · {{ m.越权原因 }}
            </li>
          </ul>
          <p v-else class="page-desc">无越权成员</p>
        </section>

        <section class="drawer-section">
          <h4>待复核清单（版本冲突隔离）</h4>
          <ul v-if="table.待复核清单.length" class="review-list">
            <li v-for="(item, i) in table.待复核清单" :key="i" data-testid="drawer-review">
              {{ item.结果类型 }} · 重叠用户：{{ item.重叠用户.join('、') }} —— {{ item.说明 }}
            </li>
          </ul>
          <p v-else-if="table.重叠用户清单.length" class="page-desc">
            重叠用户 {{ table.重叠用户清单.join('、') }} 已按 target_only 排除在正式结果外
          </p>
          <p v-else class="page-desc">无版本冲突</p>
        </section>

        <section class="drawer-section">
          <h4>V010 跨模块口径校验</h4>
          <div class="page-actions">
            <button class="btn primary" type="button" data-testid="caliber-check" @click="onCaliberCheck">
              调指标定义V010校验口径
            </button>
          </div>
          <ul v-if="caliberResult" class="review-list">
            <li v-for="c in caliberResult.checks" :key="c.指标标识" :data-testid="`caliber-${c.ok}`">
              {{ c.指标标识 }}：{{ c.message }}（结果表 {{ c.结果表口径 }} / 指标定义 {{ c.指标定义口径 }}）
            </li>
          </ul>
        </section>

        <section class="drawer-section">
          <h4>留档与转交（按V010核对）</h4>
          <div class="page-actions">
            <button class="btn" type="button" data-testid="archive-table"
                    :disabled="table.只读 || table.status === '已归档' || table.status === '已转交'" @click="onArchive">
              V010留档归档
            </button>
            <button class="btn" type="button" data-testid="handover-table"
                    :disabled="table.只读 || table.status !== '已归档'" @click="onHandover">
              转交接收方（只读）
            </button>
          </div>
          <p v-if="table.只读" class="error-text">越权范围：该结果表为共享内容，只能查看不能改动</p>
          <p v-else-if="actionMessage" class="error-text" data-testid="drawer-action-message">{{ actionMessage }}</p>
        </section>
      </div>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

import { useAbCompare, type CompareTable } from './useAbCompare'

const props = defineProps<{ table: CompareTable }>()
const emit = defineEmits<{ close: []; changed: [] }>()

const { strategyMeta, loadGroupMembers, archiveTable, handoverTable, caliberCheck, loadTables } = useAbCompare()

const showMembers = ref(false)
const memberPreview = ref<Record<string, unknown>[]>([])
const memberNote = ref('')
const caliberResult = ref<Awaited<ReturnType<typeof caliberCheck>> | null>(null)
const actionMessage = ref('')

function strategyLabel(key: string) {
  return strategyMeta.value.strategy_labels[key] ?? key
}

function isUnauthorized(member: Record<string, unknown>) {
  return props.table.越权只读清单.some((m) => m.user_id === member.user_id)
}

async function toggleMembers() {
  if (showMembers.value) {
    showMembers.value = false
    return
  }
  showMembers.value = true
  memberPreview.value = []
  memberNote.value = ''
  // 与导航页读取同一业务数据：按结果表分群集合拉取成员明细，只预览前 8 条。
  const collected: Record<string, unknown>[] = []
  for (const group of props.table.分群集合) {
    const data = await loadGroupMembers(props.table.id, group.group_id)
    collected.push(...(data.items ?? []).slice(0, 4))
  }
  memberPreview.value = collected
  memberNote.value = `仅预览前 ${collected.length} 条；越权成员带 data-unauthorized=true 标记，只读不可改`
}

async function onCaliberCheck() {
  actionMessage.value = ''
  caliberResult.value = await caliberCheck(props.table.id)
}

async function onArchive() {
  actionMessage.value = ''
  const data = await archiveTable(props.table.id)
  actionMessage.value = data.message
  if (data.ok) {
    await loadTables()
    emit('changed')
  }
}

async function onHandover() {
  actionMessage.value = ''
  const data = await handoverTable(props.table.id)
  actionMessage.value = data.message
  if (data.ok) {
    await loadTables()
    emit('changed')
  }
}
</script>

<style scoped>
.drawer-backdrop { position: fixed; inset: 0; background: rgb(15 23 42 / 35%); z-index: 30; display: flex; justify-content: flex-end; }
.drawer { width: min(720px, 92vw); height: 100%; background: #fff; box-shadow: -12px 0 40px rgb(15 23 42 / 20%); display: flex; flex-direction: column; }
.drawer-head { display: flex; justify-content: space-between; align-items: flex-start; padding: 16px 20px; border-bottom: 1px solid var(--border); }
.drawer-head h3 { margin: 0 0 4px; font-size: 16px; }
.drawer-body { padding: 16px 20px; overflow-y: auto; }
.drawer-section { margin-bottom: 18px; }
.drawer-section h4 { font-size: 13px; margin: 0 0 8px; color: #334155; }
.drawer-grid { display: grid; grid-template-columns: 110px 1fr 110px 1fr; gap: 6px 10px; margin: 0 0 10px; font-size: 12px; }
.drawer-grid dt { color: var(--muted); }
.drawer-grid dd { margin: 0; }
.member-table { margin-top: 10px; font-size: 12px; }
.review-list { margin: 6px 0 0; padding-left: 18px; font-size: 12px; color: #475569; }
.review-list li { margin-bottom: 4px; }
.trend-up { color: #16a34a; font-weight: 600; }
.trend-down { color: #dc2626; font-weight: 600; }
.page-actions { display: flex; gap: 8px; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
.badge-readonly { color: #b45309; background: #fef3c7; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
.badge-writable { color: #166534; background: #dcfce7; border-radius: 4px; padding: 2px 8px; font-size: 12px; }
</style>
