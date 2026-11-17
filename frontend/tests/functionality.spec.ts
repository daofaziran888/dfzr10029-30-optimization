import { expect, test } from '@playwright/test'
import { readFile } from 'node:fs/promises'

type ModuleCase = {
  key: string
  fields: string[]
  actions: string[]
  actionTargets: string[]
  shape: string
}

const modules: ModuleCase[] = [
  {
    "key": "metric_def",
    "fields": [
      "指标编号",
      "指标名称",
      "计算公式",
      "统计粒度",
      "时间窗口",
      "筛选条件",
      "精度位数",
      "口径版本"
    ],
    "actions": [
      "提交定义",
      "发布指标",
      "废弃指标"
    ],
    "actionTargets": [
      "已定义",
      "已发布",
      "已废弃"
    ],
    "shape": "analysis-dashboard"
  },
  {
    "key": "dimension",
    "fields": [
      "维度编号",
      "维度名称",
      "维度类型",
      "关联数据集",
      "层级结构",
      "默认取值",
      "排序规则",
      "维度状态"
    ],
    "actions": [
      "提交定义",
      "发布维度",
      "停用维度"
    ],
    "actionTargets": [
      "已定义",
      "已发布",
      "已停用"
    ],
    "shape": "crud-table"
  },
  {
    "key": "dataset",
    "fields": [
      "数据集编号",
      "数据集名称",
      "来源类型",
      "字段数量",
      "行数估算",
      "刷新周期",
      "负责人",
      "数据集状态"
    ],
    "actions": [
      "完成接入",
      "启用数据集",
      "归档数据集"
    ],
    "actionTargets": [
      "已接入",
      "使用中",
      "已归档"
    ],
    "shape": "crud-table"
  },
  {
    "key": "experiment",
    "fields": [
      "方案编号",
      "实验名称",
      "分析数据集",
      "样本范围",
      "分组字段",
      "目标度量",
      "基准区间",
      "显著阈值"
    ],
    "actions": [
      "提交设计",
      "运行实验",
      "完成实验"
    ],
    "actionTargets": [
      "已设计",
      "运行中",
      "已完成"
    ],
    "shape": "analysis-dashboard"
  },
  {
    "key": "query_builder",
    "fields": [
      "模板编号",
      "模板名称",
      "查询语句",
      "参数定义",
      "数据集范围",
      "超时秒数",
      "缓存策略",
      "模板状态"
    ],
    "actions": [
      "保存模板",
      "发布模板",
      "停用模板"
    ],
    "actionTargets": [
      "已保存",
      "已发布",
      "已停用"
    ],
    "shape": "crud-table"
  },
  {
    "key": "dashboard",
    "fields": [
      "看板编号",
      "看板名称",
      "包含图表",
      "数据刷新",
      "可见范围",
      "创建人",
      "创建时间",
      "看板状态"
    ],
    "actions": [
      "完成配置",
      "发布看板",
      "下线看板"
    ],
    "actionTargets": [
      "已发布",
      "展示中",
      "已下线"
    ],
    "shape": "crud-table"
  },
  {
    "key": "chart",
    "fields": [
      "图表编号",
      "图表名称",
      "图表类型",
      "数据来源",
      "坐标字段",
      "聚合方式",
      "颜色方案",
      "图表状态"
    ],
    "actions": [
      "保存配置",
      "发布图表",
      "停用图表"
    ],
    "actionTargets": [
      "已配置",
      "已发布",
      "已停用"
    ],
    "shape": "crud-table"
  },
  {
    "key": "data_service",
    "fields": [
      "服务编号",
      "服务名称",
      "输出数据集",
      "查询参数",
      "响应字段",
      "缓存秒数",
      "分页上限",
      "服务状态"
    ],
    "actions": [
      "保存配置",
      "发布服务",
      "停用服务"
    ],
    "actionTargets": [
      "已配置",
      "已发布",
      "已停用"
    ],
    "shape": "crud-table"
  },
  {
    "key": "alert",
    "fields": [
      "规则编号",
      "告警名称",
      "监控指标",
      "阈值条件",
      "告警级别",
      "通知方式",
      "静默时段",
      "规则状态"
    ],
    "actions": [
      "保存配置",
      "启用规则",
      "停用规则"
    ],
    "actionTargets": [
      "已配置",
      "生效中",
      "已停用"
    ],
    "shape": "crud-table"
  },
  {
    "key": "user_group",
    "fields": [
      "组编号",
      "组名称",
      "组描述",
      "成员数量",
      "数据可见性",
      "看板可见性",
      "创建日期",
      "组状态"
    ],
    "actions": [
      "停用组",
      "删除组"
    ],
    "actionTargets": [
      "已停用",
      "已删除"
    ],
    "shape": "crud-table"
  },
  {
    "key": "snapshot",
    "fields": [
      "快照编号",
      "数据集名称",
      "快照时间",
      "行数快照",
      "校验哈希",
      "快照策略",
      "存储位置",
      "快照状态"
    ],
    "actions": [
      "执行快照",
      "暂停快照",
      "标记失败"
    ],
    "actionTargets": [
      "执行中",
      "待执行",
      "执行失败"
    ],
    "shape": "job-timeline"
  },
  {
    "key": "scheduler",
    "fields": [
      "任务编号",
      "任务名称",
      "调度类型",
      "执行周期",
      "上次执行",
      "下次执行",
      "依赖关系",
      "任务状态"
    ],
    "actions": [
      "立即执行",
      "暂停任务",
      "标记失败"
    ],
    "actionTargets": [
      "执行中",
      "待执行",
      "执行失败"
    ],
    "shape": "job-timeline"
  },
  {
    "key": "cache",
    "fields": [
      "缓存编号",
      "缓存目标",
      "缓存策略",
      "过期秒数",
      "最大容量",
      "命中统计",
      "淘汰策略",
      "缓存状态"
    ],
    "actions": [
      "保存配置",
      "启用缓存",
      "停用缓存"
    ],
    "actionTargets": [
      "已配置",
      "生效中",
      "已停用"
    ],
    "shape": "crud-table"
  },
  {
    "key": "pipeline",
    "fields": [
      "节点编号",
      "输入数据集",
      "分析算子",
      "输出结果",
      "执行顺序",
      "依赖节点",
      "失败策略",
      "节点状态"
    ],
    "actions": [
      "提交配置",
      "启动节点",
      "标记失败"
    ],
    "actionTargets": [
      "已配置",
      "运行中",
      "失败"
    ],
    "shape": "dag-graph"
  },
  {
    "key": "model",
    "fields": [
      "模型编号",
      "模型名称",
      "模型类型",
      "训练数据集",
      "特征字段",
      "目标字段",
      "评估指标",
      "模型状态"
    ],
    "actions": [
      "提交训练",
      "启动评估",
      "部署模型"
    ],
    "actionTargets": [
      "已训练",
      "评估中",
      "已部署"
    ],
    "shape": "dag-graph"
  },
  {
    "key": "data_mart",
    "fields": [
      "表编号",
      "表名称",
      "主题域",
      "事实粒度",
      "关联维度",
      "度量字段",
      "刷新周期",
      "表状态"
    ],
    "actions": [
      "提交建模",
      "发布集市",
      "下线集市"
    ],
    "actionTargets": [
      "已建模",
      "已发布",
      "已下线"
    ],
    "shape": "dag-graph"
  },
  {
    "key": "export",
    "fields": [
      "任务编号",
      "导出对象",
      "导出格式",
      "筛选条件",
      "数据行数",
      "导出时间",
      "文件大小",
      "任务状态"
    ],
    "actions": [
      "开始导出",
      "重新导出",
      "标记失败"
    ],
    "actionTargets": [
      "导出中",
      "待导出",
      "导出失败"
    ],
    "shape": "job-timeline"
  },
  {
    "key": "audit",
    "fields": [
      "记录编号",
      "操作类型",
      "操作人",
      "操作对象",
      "操作时间",
      "变更内容",
      "审计结果",
      "记录状态"
    ],
    "actions": [
      "提交审计",
      "标记异常"
    ],
    "actionTargets": [
      "已审计",
      "异常"
    ],
    "shape": "crud-table"
  }
]
const repoKind = 'fullstack'
const crudModules = modules.filter(m => m.shape === 'crud-table')
const dagModules = modules.filter(m => m.shape === 'dag-graph')
const timelineModules = modules.filter(m => m.shape === 'job-timeline')
const analysisModules = modules.filter(m => m.shape === 'analysis-dashboard')

function parseCsv(text: string): string[][] {
  const records: string[][] = []
  let row: string[] = []
  let cell = ''
  let quoted = false
  const input = text.replace(/^\uFEFF/, '')
  for (let index = 0; index < input.length; index++) {
    const char = input[index]
    if (quoted) {
      if (char === '"' && input[index + 1] === '"') { cell += '"'; index++ }
      else if (char === '"') { quoted = false }
      else { cell += char }
    } else if (char === '"' && cell === '') { quoted = true }
    else if (char === ',') { row.push(cell); cell = '' }
    else if (char === '\n') {
      row.push(cell.replace(/\r$/, ''))
      if (row.some(v => v !== '')) records.push(row)
      row = []; cell = ''
    } else { cell += char }
  }
  row.push(cell.replace(/\r$/, ''))
  if (row.some(v => v !== '')) records.push(row)
  return records
}

test('CRUD模块：筛选、导出、登记、动作、指标全链路', async ({ page }) => {
  test.setTimeout(300_000)
  const browserErrors: string[] = []
  page.on('pageerror', e => browserErrors.push(e.message))
  page.on('response', r => { if (r.url().includes('/api/') && r.status()>=400) browserErrors.push(`${r.status()} ${r.url()}`) })
  if (crudModules.length === 0) { test.skip(); return }

  for (const mod of crudModules) {
    await page.goto(`/${mod.key}`)
    await page.waitForTimeout(3000)
    const bodyRows = page.locator('tbody tr[data-testid^="row-"]')
    await expect(bodyRows).toHaveCount(3)
    const firstValue = await bodyRows.nth(0).locator('td').nth(0).innerText()

    await page.getByTestId(`filter-${mod.fields[0]}`).fill(firstValue)
    await page.getByTestId('query').click()
    await expect(bodyRows).toHaveCount(1)
    await page.getByTestId('reset').click()
    await expect(bodyRows).toHaveCount(3)

    const downloadPromise = page.waitForEvent('download')
    await page.getByTestId('export').click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe(`${mod.key}.csv`)

    const createdValues = mod.fields.map((f, i) => `验收-${mod.key}-${i+1}`)
    await page.getByTestId('open-create').click()
    await expect(page.getByTestId('create-modal')).toBeVisible()
    for (const [i, field] of mod.fields.entries()) {
      await page.getByTestId(`create-${field}`).fill(createdValues[i])
    }
    await page.getByTestId('submit-create').click()
    await expect(page.getByTestId('create-modal')).toHaveCount(0)
    await expect(bodyRows).toHaveCount(4)

    const createdRow = page.locator('tbody tr').filter({ hasText: createdValues[0] })
    for (const [i, action] of mod.actions.entries()) {
      await createdRow.getByRole('button', { name: action, exact: true }).click()
      await expect(createdRow).toHaveAttribute('data-status', mod.actionTargets[i])
    }
  }

  expect(browserErrors).toEqual([])
})

test('DAG拓扑模块：节点渲染、详情、动作、导出', async ({ page }) => {
  test.setTimeout(300_000)
  const browserErrors: string[] = []
  page.on('pageerror', e => browserErrors.push(e.message))
  page.on('response', r => { if (r.url().includes('/api/') && r.status()>=400) browserErrors.push(`${r.status()} ${r.url()}`) })
  if (dagModules.length === 0) { test.skip(); return }

  for (const mod of dagModules) {
    await page.goto('/')
    // 数据集市默认按用户组授权过滤；E2E 先切回平台管理视图再走维护流程。
    const groupInput = page.getByTestId('session-group')
    if (await groupInput.count()) {
      await groupInput.fill('')
      await page.waitForTimeout(1500)
    }
    await page.goto(`/${mod.key}`)
    await page.waitForTimeout(3000)
    await expect(page.locator('svg.dag-svg')).toBeVisible()
    const nodes = page.locator('g.dag-node')
    const count = await nodes.count()
    expect(count).toBeGreaterThanOrEqual(3)

    await nodes.first().click()
    await expect(page.getByTestId('dag-detail')).toBeVisible()

    const downloadPromise = page.waitForEvent('download')
    await page.getByTestId('export').click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe(`${mod.key}.csv`)

    await page.getByTestId('open-create').click()
    await expect(page.getByTestId('create-modal')).toBeVisible()
    for (const [i, field] of mod.fields.slice(0,3).entries()) {
      await page.locator('.create-field input').nth(i).fill(`E2E-${mod.key}-${i}`)
    }
    await page.getByTestId('submit-create').click()
    await expect(page.getByTestId('create-modal')).toHaveCount(0)
  }

  expect(browserErrors).toEqual([])
})

test('时间线模块：甘特条渲染、日期筛选、日志查看、登记', async ({ page }) => {
  test.setTimeout(300_000)
  const browserErrors: string[] = []
  page.on('pageerror', e => browserErrors.push(e.message))
  page.on('response', r => { if (r.url().includes('/api/') && r.status()>=400) browserErrors.push(`${r.status()} ${r.url()}`) })
  if (timelineModules.length === 0) { test.skip(); return }

  for (const mod of timelineModules) {
    await page.goto(`/${mod.key}`)
    await expect(page.locator('.timeline-bar').first()).toBeVisible({ timeout: 10000 })
    const bars = page.locator('.timeline-bar')
    const count = await bars.count()
    expect(count).toBeGreaterThanOrEqual(3)

    await bars.first().click()
    await expect(page.getByTestId('timeline-log')).toBeVisible()

    const downloadPromise = page.waitForEvent('download')
    await page.getByTestId('export').click()
    const download = await downloadPromise
    expect(download.suggestedFilename()).toBe(`${mod.key}.csv`)

    await page.getByTestId('open-create').click()
    await expect(page.getByTestId('create-modal')).toBeVisible()
    for (const [i, field] of mod.fields.slice(0,3).entries()) {
      await page.locator('.create-field input').nth(i).fill(`E2E-${mod.key}-${i}`)
    }
    await page.getByTestId('submit-create').click()
    await expect(page.getByTestId('create-modal')).toHaveCount(0)
  }

  expect(browserErrors).toEqual([])
})

test('分析看板模块：KPI卡片、运行分析、图表渲染', async ({ page }) => {
  test.setTimeout(300_000)
  const browserErrors: string[] = []
  page.on('pageerror', e => browserErrors.push(e.message))
  page.on('response', r => { if (r.url().includes('/api/') && r.status()>=400) browserErrors.push(`${r.status()} ${r.url()}`) })
  if (analysisModules.length === 0) { test.skip(); return }

  for (const mod of analysisModules) {
    await page.goto(`/${mod.key}`)
    await expect(page.getByTestId('kpi-card').first()).toBeVisible({ timeout: 10000 })
    const kpiCards = page.getByTestId('kpi-card')
    const kpiCount = await kpiCards.count()
    expect(kpiCount).toBeGreaterThanOrEqual(2)
    await expect(kpiCards.first().locator('strong')).toBeVisible()

    await page.getByTestId('run-analysis').click()
    await expect(page.locator('.analysis-bar').first()).toBeVisible({ timeout: 5000 })
    await expect(page.locator('.data-table tbody tr').first()).toBeVisible({ timeout: 5000 })
  }

  expect(browserErrors).toEqual([])
})

test('概览汇总', async ({ page }) => {
  test.setTimeout(300_000)
  await page.goto('/')
  await expect(page.locator('.stat-value').nth(1)).toBeVisible()
  // 验证概览页加载正常即可，不硬编码精确计数（取决于各模块 E2E 登记成功数）
})
