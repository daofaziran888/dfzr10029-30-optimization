<template>
  <section class="page" data-module="mart_authorization">
    <header class="page-head">
      <div>
        <h2>集市授权过滤记录</h2>
        <p class="page-desc">
          发布集市授权过滤记录并按主版本边界核对；同一来源段只保留一个有效版本，
          回退后仍可追溯同一段来源。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" data-testid="open-create" @click="openPublish">发布授权过滤记录</button>
        <button class="btn" type="button" data-testid="reconcile" @click="reconcile">核对主版本边界</button>
        <button class="btn" type="button" data-testid="export" @click="exportRows">导出记录清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>记录状态</span>
        <select v-model="statusFilter" data-testid="filter-status">
          <option value="">全部状态</option>
          <option v-for="s in statuses" :key="s" :value="s">{{ s }}</option>
        </select>
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>主版本边界</th>
          <th>核对说明</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="row in rows"
          :key="String(row.id)"
          :data-testid="`row-${row.id}`"
          :data-status="String(row.status)"
        >
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row['主版本边界'] ?? '—' }}</td>
          <td class="reason-cell">{{ row['核对说明'] || '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >{{ action }}</button>
            <button class="link" type="button" :data-testid="`trace-${row.id}`" @click="openTrace(row)">追溯</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 3" class="empty-state">暂无集市授权过滤记录，可先发布一条授权过滤记录</td>
        </tr>
      </tbody>
    </table>

    <div v-if="traceData" class="trace-panel" data-testid="trace-panel">
      <header class="trace-head">
        <strong>来源段追溯：{{ traceData['来源段'] }}</strong>
        <button class="btn ghost" type="button" data-testid="close-trace" @click="traceData = null">关闭</button>
      </header>
      <p>用户组：{{ traceData['用户组'] }} {{ traceData['组名称'] ? `（${traceData['组名称']}）` : '' }} · 当前有效版本：{{ traceData['当前有效版本'] || '无' }}</p>
      <table class="data-table">
        <thead>
          <tr><th>记录编号</th><th>版本</th><th>主版本</th><th>处理次序</th><th>版本状态</th><th>核对状态</th><th>记录状态</th><th>操作人</th><th>说明</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in traceData['版本链']" :key="String(item['记录编号'])">
            <td>{{ item['记录编号'] }}</td>
            <td>v{{ item['版本号'] }}</td>
            <td>v{{ item['主版本号'] }} / 边界 {{ item['主版本边界'] }}</td>
            <td>{{ item['处理次序'] }}</td>
            <td>{{ item['版本状态'] }}</td>
            <td>{{ item['核对状态'] }}</td>
            <td>{{ item['记录状态'] }}</td>
            <td>{{ item['操作人'] }}</td>
            <td class="reason-cell">{{ item['核对说明'] || '—' }}</td>
          </tr>
        </tbody>
      </table>
      <p class="trace-flow">
        结果数据流：
        <span v-for="(flow, i) in traceData['结果数据流']" :key="String(flow['表编号'])">
          {{ i ? '、' : '' }}{{ flow['表编号'] }}（{{ flow['主题域'] }}，维度 {{ flow['关联维度'] }}）
        </span>
        <span v-if="!traceData['结果数据流'].length">无可关联的集市表</span>
      </p>
    </div>

    <div v-if="reconcileResult" class="trace-panel" data-testid="reconcile-result">
      <header class="trace-head">
        <strong>核对主版本边界 {{ reconcileResult['主版本边界'] }}</strong>
        <button class="btn ghost" type="button" @click="reconcileResult = null">关闭</button>
      </header>
      <p>消费 {{ reconcileResult['消费记录数'] }} 条，有效 {{ reconcileResult['有效版本'].length }} 条，
        冲突 {{ reconcileResult['冲突待核对'].length }} 条。</p>
      <ul class="conflict-list">
        <li v-for="item in reconcileResult['冲突待核对']" :key="String(item['记录编号'])">
          {{ item['记录编号'] }} · {{ item['用户组'] }} · {{ item['主题域'] }} —— {{ item['核对说明'] }}
        </li>
      </ul>
    </div>

    <div v-if="showPublish" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitPublish">
        <h3>发布授权过滤记录</h3>
        <label class="create-field"><span>用户组</span><input v-model="publishValues['用户组']" data-testid="create-用户组" placeholder="USER-0001" required /></label>
        <label class="create-field"><span>主题域</span><input v-model="publishValues['主题域']" data-testid="create-主题域" placeholder="销售域" required /></label>
        <label class="create-field"><span>授权维度</span><input v-model="publishValues['授权维度']" data-testid="create-授权维度" placeholder="DIME-0001, DIME-0002" /></label>
        <label class="create-field"><span>来源段</span><input v-model="publishValues['来源段']" data-testid="create-来源段" placeholder="留空则按 用户组:主题域" /></label>
        <label class="create-field"><span>处理次序</span><input v-model="publishValues['处理次序']" data-testid="create-处理次序" placeholder="留空自动递增" /></label>
        <label class="create-field"><span>主版本号</span><input v-model="publishValues['主版本号']" data-testid="create-主版本号" placeholder="留空取版本号" /></label>
        <label class="create-field"><span>主版本边界</span><input v-model="publishValues['主版本边界']" data-testid="create-主版本边界" placeholder="留空取主版本号" /></label>
        <label class="create-field"><span>授权依据</span><input v-model="publishValues['授权依据']" data-testid="create-授权依据" placeholder="主题域授权：销售域" /></label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showPublish = false">取消</button>
          <button class="btn primary" type="submit" data-testid="submit-create" :disabled="publishing">
            {{ publishing ? '提交中…' : '确认发布' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条集市授权过滤记录</span>
      <span v-if="errorMessage" class="error-text" data-testid="auth-error">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { actorHeaders, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

type Row = Record<string, any>

const session = useSessionStore()

const ENDPOINT = '/api/mart_authorization'
const columns = [
  "记录编号", "用户组", "主题域", "授权维度", "来源段",
  "版本号", "主版本号", "处理次序", "版本状态", "核对状态", "记录状态",
]
const actions = ["提交核对", "核对通过", "标记冲突", "回退版本", "归档记录"]
const statuses = ["草稿", "待核对", "已生效", "冲突", "已回退", "已归档"]
const filterFields = ["记录编号", "用户组", "主题域"]

const rows = ref<Row[]>([])
const total = ref(0)
const statusFilter = ref('')
const filters = ref<Record<string, string>>({})
const errorMessage = ref('')
const summaryCounts = ref<Record<string, number>>({})
const showPublish = ref(false)
const publishing = ref(false)
const publishValues = ref<Record<string, string>>({})
const traceData = ref<Row | null>(null)
const reconcileResult = ref<Row | null>(null)

const stats = computed(() => [
  { label: "记录总数", value: summaryCounts.value['记录总数'] ?? total.value },
  { label: "有效版本", value: summaryCounts.value['有效版本'] ?? 0 },
  { label: "冲突待核对", value: summaryCounts.value['冲突待核对'] ?? 0 },
  { label: "已回退版本", value: summaryCounts.value['已回退版本'] ?? 0 },
])

function resetFilters() {
  filters.value = {}
  statusFilter.value = ''
  void reload()
}

async function loadSummary() {
  try {
    const response = await request(`${ENDPOINT}/summary`)
    if (!response.ok) return
    summaryCounts.value = await response.json()
  } catch {
    summaryCounts.value = {}
  }
}

async function reload() {
  errorMessage.value = ''
  const params = new URLSearchParams(filters.value as Record<string, string>)
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}?${params.toString()}`)
    if (!response.ok) throw new Error('集市授权过滤记录读取失败')
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '集市授权过滤记录读取失败'
  }
  await loadSummary()
}

async function exportRows() {
  errorMessage.value = ''
  const params = new URLSearchParams(filters.value as Record<string, string>)
  if (statusFilter.value) params.set('status', statusFilter.value)
  try {
    const response = await request(`${ENDPOINT}/export?${params.toString()}`)
    if (!response.ok) throw new Error('导出失败，请稍后重试')
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = 'mart_authorization.csv'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openPublish() {
  publishValues.value = { '用户组': 'USER-0001', '主题域': '销售域' }
  errorMessage.value = ''
  showPublish.value = true
}

async function submitPublish() {
  publishing.value = true
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      headers: actorHeaders(session.operator, session.role),
      body: JSON.stringify({ values: publishValues.value }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '发布失败')
    showPublish.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '发布失败'
  } finally {
    publishing.value = false
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      headers: actorHeaders(session.operator, session.role),
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '动作未生效')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reconcile() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/reconcile`, {
      method: 'POST',
      headers: actorHeaders(session.operator, session.role),
      body: JSON.stringify({
        values: filters.value['用户组'] ? { 用户组: filters.value['用户组'] } : {},
      }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) throw new Error(payload.message || '核对失败')
    reconcileResult.value = payload.entry
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '核对失败'
  }
}

async function openTrace(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/trace`)
    if (!response.ok) throw new Error('追溯信息读取失败')
    traceData.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '追溯信息读取失败'
  }
}

onMounted(reload)
</script>
