<template>
  <section class="page" data-module="data_mart">
    <header class="page-head">
      <div>
        <h2>数据集市</h2>
        <p class="page-desc">
          维护集市表，按用户组授权的主题域与关联维度读取集市数据。
          主题域授权和关联维度过滤一起生效，避免集市表可见但维度明细泄露。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" data-testid="open-create" @click="openCreate">登记集市表</button>
        <button class="btn" type="button" data-testid="export" @click="exportRows">导出关系清单</button>
      </div>
    </header>

    <form class="filter-bar mart-scope" @submit.prevent="reload">
      <label> <span>当前用户组</span>
        <input v-model="groupInput" data-testid="mart-group" placeholder="用户组编号或名称，如 USER-0001" />
      </label>
      <label><span>授权口径</span>
        <select v-model="authMode" data-testid="mart-auth-mode">
          <option value="主题域">按主题域授权</option>
          <option value="关联维度">按关联维度归属授权</option>
        </select>
      </label>
      <label><span>主题域</span>
        <select v-model="domain" data-testid="mart-domain">
          <option value="">全部可访问主题域</option>
          <option v-for="item in domains" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn primary" type="submit" data-testid="query">查询</button>
      <button class="btn ghost" type="button" data-testid="reset" @click="resetScope">重置条件</button>
      <button class="btn" type="button" data-testid="export-authorized" @click="exportRows">导出授权结果</button>
    </form>

    <div v-if="authSummary" class="scope-summary" data-testid="mart-summary">
      <article class="stat-card">
        <span class="stat-label">授权主题域</span>
        <strong class="stat-value">{{ summaryDomains }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">授权维度</span>
        <strong class="stat-value">{{ summaryDimensions }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">可读集市表</span>
        <strong class="stat-value">{{ authSummary['可读表数'] }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">未授权集市表</span>
        <strong class="stat-value">{{ authSummary['未授权表数'] }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">授权口径</span>
        <strong class="stat-value">{{ authSummary['授权口径'] }}</strong>
      </article>
    </div>
    <p v-if="authNotice" class="scope-notice" data-testid="mart-notice">{{ authNotice }}</p>

    <div class="dag-wrap" ref="dagRef">
      <svg class="dag-svg" :viewBox="`0 0 ${svgW} ${svgH}`">
        <defs><marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6" fill="#94a3b8"/></marker></defs>
        <g v-for="edge in graph.edges" :key="edge.from+'-'+edge.to">
          <line class="dag-edge" :x1="nodePos[edge.from]?.x||0" :y1="nodePos[edge.from]?.y||0" :x2="nodePos[edge.to]?.x||0" :y2="nodePos[edge.to]?.y||0"/>
          <text :x="(nodePos[edge.from]?.x+nodePos[edge.to]?.x)/2" :y="(nodePos[edge.from]?.y+nodePos[edge.to]?.y)/2 - 6" font-size="10" fill="#64748b" text-anchor="middle">{{ edge.label }}</text>
        </g>
        <g v-for="node in graph.nodes" :key="node.id" :class="['dag-node', {selected: selectedNode?.id===node.id}]" @click="selectNode(node)" @mousedown="startDrag($event, node)">
          <rect :x="nodePos[node.id]?.x - 60" :y="nodePos[node.id]?.y - 20" width="120" height="40" rx="6" :fill="nodeColor(node.status)"/>
          <text :x="nodePos[node.id]?.x" :y="nodePos[node.id]?.y + 4" text-anchor="middle">{{ node.name || node.label }}</text>
        </g>
      </svg>
      <p v-if="!graph.nodes.length" class="scope-empty" data-testid="mart-empty">当前用户组没有可访问的主题域集市表</p>
    </div>

    <div v-if="selectedNode" class="dag-detail" data-testid="dag-detail">
      <dl><dt>编号</dt><dd>{{ selectedNode.id }}</dd></dl>
      <dl><dt>名称</dt><dd>{{ selectedNode.name || selectedNode.label }}</dd></dl>
      <dl v-for="f in detailFields" :key="f"><dt>{{ f }}</dt><dd>{{ selectedNode[f] ?? '—' }}</dd></dl>
      <div style="grid-column:1/-1; margin-top:8px; display:flex; gap:6px; flex-wrap:wrap;">
        <button v-for="action in actions" :key="action" class="btn" :data-testid="`action-${selectedNode.id}-${action}`" @click="runAction(action, selectedNode)">{{ action }}</button>
      </div>
      <div style="grid-column:1/-1" class="trace-flow" data-testid="mart-authorizations">
        <span v-if="selectedAuths.length">
          关联授权过滤记录：
          <span v-for="(item, i) in selectedAuths" :key="String(item['记录编号'])">
            {{ i ? '、' : '' }}{{ item['记录编号'] }}（v{{ item['版本号'] }} · {{ item['版本状态'] }} · {{ item['核对状态'] }}）
          </span>
        </span>
        <span v-else>关联授权过滤记录：无（该主题域尚未发布授权口径）</span>
      </div>
    </div>

    <div v-if="tableRows.length" class="data-table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>表编号</th><th>表名称</th><th>主题域</th><th>关联维度</th>
            <th>被过滤维度</th><th>度量字段</th><th>授权依据</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in tableRows" :key="String(row['表编号'])" :data-testid="`mart-row-${row['表编号']}`">
            <td>{{ row['表编号'] }}</td>
            <td>{{ row['表名称'] }}</td>
            <td>{{ row['主题域'] }}</td>
            <td>{{ row['可读维度'] || '—' }}</td>
            <td>{{ row['被过滤维度'] || '—' }}</td>
            <td>{{ row['度量字段'] || '（跨主题度量已屏蔽）' }}</td>
            <td>{{ row['授权依据'] }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="deniedRows.length" class="denied-wrap" data-testid="mart-denied">
      <h3>未授权主题域（不可读取度量）</h3>
      <ul>
        <li v-for="item in deniedRows" :key="String(item['表编号'])">
          {{ item['表编号'] }} · {{ item['表名称'] }} · {{ item['主题域'] }} —— {{ item['授权依据'] }}
        </li>
      </ul>
    </div>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate"><h3>登记集市表</h3>
        <label class="create-field"><span>表编号</span><input v-model="createValues['表编号']" placeholder="请输入表编号" required /></label>
        <label class="create-field"><span>表名称</span><input v-model="createValues['表名称']" placeholder="请输入表名称" required /></label>
        <label class="create-field"><span>主题域</span><input v-model="createValues['主题域']" placeholder="请输入主题域" required /></label>
        <label class="create-field"><span>关联维度</span><input v-model="createValues['关联维度']" placeholder="DIME-0001, DIME-0002" /></label>
        <label class="create-field"><span>度量字段</span><input v-model="createValues['度量字段']" placeholder="销售额, 订单数" /></label>
        <div style="display:flex;gap:8px;justify-content:flex-end;margin-top:12px">
          <button class="btn" type="button" @click="showCreate=false">取消</button>
          <button class="btn primary" type="submit" data-testid="submit-create">提交</button>
        </div>
      </form>
    </div>
    <footer class="page-foot">
      <span>{{ graph.nodes.length }} 个节点 · {{ authSummary ? `${authSummary['授权口径']}口径` : '全量维护视图' }}</span>
      <span v-if="errorMessage" class="error-text" data-testid="mart-error">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { actorHeaders, request } from '@/api/client'
import { useSessionStore } from '@/stores/session'

const ENDPOINT = '/api/data_mart'
const columns = ["表编号", "表名称", "主题域", "事实粒度", "关联维度", "度量字段", "刷新周期", "表状态"]
const actions = ["提交建模", "发布集市", "下线集市"]
const STATUS_COLORS: Record<string, string> = { '草稿': '#e2e8f0', '已建模': '#fef3c7', '已发布': '#d1fae5', '已下线': '#fee2e2' }
const nodeColor = (s: string) => STATUS_COLORS[s] || '#e2e8f0'

const graph = reactive<{ nodes: any[], edges: any[] }>({ nodes: [], edges: [] })
const nodePos = ref<Record<number, { x: number; y: number }>>({})
const selectedNode = ref<any>(null)
const detailFields = computed(() => [
  ...columns.filter((f: string) => !['id', 'name', 'label', 'status'].includes(f)),
  '可读维度', '被过滤维度', '授权依据', '授权口径',
])
const svgW = ref(800)
const svgH = ref(400)
const errorMessage = ref('')
const showCreate = ref(false)
const createValues = ref<Record<string, string>>({})

const session = useSessionStore()
const groupInput = ref(session.userGroup)
const authMode = ref('主题域')
const domain = ref('')
const domains = ref<string[]>([])
const tableRows = ref<any[]>([])
const deniedRows = ref<any[]>([])
const authSummary = ref<any>(null)
const authNotice = ref('')

const summaryDomains = computed(() => (authSummary.value?.['授权主题域'] || []).join('、') || '—')
const summaryDimensions = computed(() => {
  const dims = authSummary.value?.['授权维度'] || []
  if (authSummary.value?.['维度授权已声明'] === false) return '全部维度'
  return dims.join('、') || '—'
})

let dragNode: any = null
const dagRef = ref<HTMLElement | null>(null)

function layout(nodes: any[]) {
  const h = Math.max(400, nodes.length * 80)
  svgW.value = 800
  svgH.value = h
  const pos: Record<number, { x: number; y: number }> = {}
  nodes.forEach((n, i) => { pos[n.id] = { x: 120 + (i % 5) * 150, y: 50 + Math.floor(i / 5) * 80 } })
  nodePos.value = pos
}

const selectedAuths = ref<any[]>([])

async function selectNode(node: any) {
  if (selectedNode.value?.id === node.id) {
    selectedNode.value = null
    selectedAuths.value = []
    return
  }
  selectedNode.value = node
  selectedAuths.value = []
  try {
    const response = await request(`${ENDPOINT}/${node.id}/authorizations`)
    if (!response.ok) return
    const payload = await response.json()
    selectedAuths.value = payload.items || []
  } catch {
    selectedAuths.value = []
  }
}

function startDrag(e: MouseEvent, node: any) {
  dragNode = node
  const onMove = (ev: MouseEvent) => { if (!dragNode) return; nodePos.value[node.id] = { x: ev.offsetX, y: ev.offsetY } }
  const onUp = () => {
    dragNode = null
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
}

function scopeQuery(): string {
  const params = new URLSearchParams()
  if (groupInput.value.trim()) params.set('group', groupInput.value.trim())
  params.set('auth_mode', authMode.value)
  if (domain.value) params.set('domain', domain.value)
  return params.toString()
}

async function loadAccess() {
  tableRows.value = []
  deniedRows.value = []
  authSummary.value = null
  authNotice.value = ''
  const group = groupInput.value.trim()
  if (!group) return
  try {
    const response = await request(`/api/data_mart/access?${scopeQuery()}`)
    if (!response.ok) throw new Error('授权范围内集市数据读取失败')
    const payload = await response.json()
    tableRows.value = payload.items || []
    authSummary.value = payload.summary || null
    deniedRows.value = payload.summary?.['未授权表'] || []
    if (!payload.summary?.授权主题域?.length) {
      authNotice.value = '该用户组没有授权主题域，集市表与其维度明细均不可读取。'
    } else if (!tableRows.value.length) {
      authNotice.value = '该用户组在授权口径下没有可读取的集市表。'
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '授权数据加载失败'
  }
}

async function loadDomains() {
  const group = groupInput.value.trim()
  const query = group ? `?group=${encodeURIComponent(group)}` : ''
  try {
    const response = await request(`${ENDPOINT}/domains${query}`)
    if (!response.ok) return
    const payload = await response.json()
    domains.value = payload.domains || []
    if (domain.value && !domains.value.includes(domain.value)) domain.value = ''
  } catch {
    domains.value = []
  }
}

async function reload() {
  errorMessage.value = ''
  selectedNode.value = null
  const group = groupInput.value.trim()
  const query = group ? `?group=${encodeURIComponent(group)}&auth_mode=${encodeURIComponent(authMode.value)}` : ''
  try {
    const response = await request(`${ENDPOINT}${query}`)
    if (!response.ok) throw new Error('加载失败')
    const data = await response.json()
    graph.nodes = data.nodes || []
    graph.edges = data.edges || []
    layout(graph.nodes)
  } catch {
    errorMessage.value = '加载失败'
  }
  await loadDomains()
  await loadAccess()
}

function resetScope() {
  authMode.value = '主题域'
  domain.value = ''
  errorMessage.value = ''
  void reload()
}

async function runAction(action: string, node: any) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${node.id}/actions`, {
      method: 'POST',
      headers: actorHeaders(session.operator, session.role),
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) throw new Error(payload.message || '操作失败')
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

function openCreate() { createValues.value = {}; showCreate.value = true }

async function submitCreate() {
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      headers: actorHeaders(session.operator, session.role),
      body: JSON.stringify({ values: createValues.value }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) throw new Error(payload.message || '创建失败')
    showCreate.value = false
    await reload()
  } catch (error: any) {
    errorMessage.value = error.message
  }
}

function exportRows() {
  const group = groupInput.value.trim()
  const query = new URLSearchParams()
  if (group) query.set('group', group)
  query.set('auth_mode', authMode.value)
  window.open(`${ENDPOINT}/export?${query.toString()}`, '_blank')
}

watch(() => session.userGroup, (value) => {
  groupInput.value = value
  void reload()
})

onMounted(reload)
</script>
