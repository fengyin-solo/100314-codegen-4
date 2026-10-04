<template>
  <section class="page" data-module="succession">
    <header class="page-head">
      <div>
        <h2>采掘接续计划</h2>
        <p class="page-desc">一个采煤工作面挂一条台账，计划按版本管理：调整另出新版、原版保留，实际进度登记后回写台账并按当前版本口径重算偏差。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openForm('create')">登记接续计划</button>
        <button class="btn" type="button" @click="exportRows">导出接续计划台账</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>工作面编号</span>
        <input v-model="filters.keyword" placeholder="按工作面编号检索" />
      </label>
      <label class="filter-item">
        <span>接续方式</span>
        <input v-model="filters.mode" placeholder="按当前版本接续方式检索" />
      </label>
      <label class="filter-item">
        <span>台账状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <div v-if="activeForm" class="form-panel">
      <h3>{{ formTitle }}</h3>
      <div class="form-grid">
        <label v-for="field in formFields" :key="field.key" class="filter-item">
          <span>{{ field.label }}</span>
          <select v-if="field.key === '进度口径'" v-model="formValues[field.key]">
            <option v-for="caliber in calibers" :key="caliber" :value="caliber">{{ caliber }}</option>
          </select>
          <input v-else v-model="formValues[field.key]" :placeholder="field.placeholder" />
        </label>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="submitForm">提交</button>
        <button class="btn ghost" type="button" @click="activeForm = ''">取消</button>
      </div>
    </div>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :class="{ selected: selectedId === row.id }">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="showDetail(row)">版本记录</button>
            <button class="link" type="button" @click="openForm('version', row)">另出新版</button>
            <button v-if="row['待批准']" class="link" type="button" @click="approve(row)">批准版本</button>
            <button class="link" type="button" @click="openForm('progress', row)">登记进度</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无采掘接续数据，可先登记接续计划</td>
        </tr>
      </tbody>
    </table>

    <section v-if="detail" class="detail-panel">
      <h3>{{ detail['工作面编号'] }} · 版本记录（当前 {{ detail['当前版本'] }}，各处读取同源）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in versionColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="version in detail.versions" :key="version['版本号']" :class="{ selected: version['是否当前'] }">
            <td>V{{ version['版本号'] }}{{ version['是否当前'] ? '（当前）' : '' }}</td>
            <td>{{ version['版本状态'] }}</td>
            <td>{{ version['接续方式'] }}</td>
            <td>{{ version['计划开工月份'] }}</td>
            <td>{{ version['计划完工月份'] }}</td>
            <td>{{ version['衔接前工作面'] || '—' }}</td>
            <td>{{ version['衔接后工作面'] || '—' }}</td>
            <td>{{ version['进度口径'] }}</td>
            <td>{{ version['偏差(月)'] ?? '待定' }}</td>
            <td>{{ version['调整说明'] }}</td>
          </tr>
        </tbody>
      </table>
      <h3>实际进度登记</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in progressColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(item, index) in detail.progress" :key="index">
            <td>{{ item['登记月份'] }}</td>
            <td>{{ item['实际开工月份'] || '—' }}</td>
            <td>{{ item['实际完工月份'] || '—' }}</td>
            <td>{{ item['进度说明'] || '—' }}</td>
          </tr>
          <tr v-if="!detail.progress.length">
            <td :colspan="progressColumns.length" class="empty-state">尚未登记实际进度</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ total }} 条采掘接续记录</span>
      <span v-if="noticeMessage" class="notice-text">{{ noticeMessage }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/succession'
const columns = ["工作面编号", "工作面名称", "所在采区", "当前版本", "接续方式", "计划开工月份", "计划完工月份", "实际开工月份", "实际完工月份", "偏差(月)", "衔接结论", "台账状态"]
const versionColumns = ["版本", "版本状态", "接续方式", "计划开工月份", "计划完工月份", "衔接前工作面", "衔接后工作面", "进度口径", "偏差(月)", "调整说明"]
const progressColumns = ["登记月份", "实际开工月份", "实际完工月份", "进度说明"]
const statuses = ["接续正常", "衔接冲突", "已采完"]
const calibers = ["开工口径", "完工口径", "开完工口径"]

const createFields = [
  { key: '工作面编号', label: '工作面编号', placeholder: '如 FACE-2102' },
  { key: '工作面名称', label: '工作面名称', placeholder: '如 2102综采工作面' },
  { key: '所在采区', label: '所在采区', placeholder: '如 二采区' },
  { key: '接续方式', label: '接续方式', placeholder: '如 走向长壁后退式' },
  { key: '计划开工月份', label: '计划开工月份', placeholder: 'YYYY-MM' },
  { key: '计划完工月份', label: '计划完工月份', placeholder: 'YYYY-MM' },
  { key: '衔接前工作面', label: '衔接前工作面', placeholder: '选填，如 FACE-2101' },
  { key: '衔接后工作面', label: '衔接后工作面', placeholder: '选填' },
  { key: '进度口径', label: '进度口径', placeholder: '' },
  { key: '调整说明', label: '调整说明', placeholder: '选填' },
]
const versionFields = createFields.slice(3)
const progressFields = [
  { key: '实际开工月份', label: '实际开工月份', placeholder: 'YYYY-MM' },
  { key: '实际完工月份', label: '实际完工月份', placeholder: 'YYYY-MM' },
  { key: '进度说明', label: '进度说明', placeholder: '选填' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const noticeMessage = ref('')
const filters = ref<Record<string, string>>({ keyword: '', mode: '', status: '' })
const detail = ref<Record<string, any> | null>(null)
const selectedId = ref<string | number | boolean | null>(null)
const activeForm = ref('')
const formValues = ref<Record<string, string>>({})

const stats = computed(() => {
  const deviations = rows.value
    .map((row) => Number(row['偏差(月)']))
    .filter((value) => Number.isFinite(value))
  const average = deviations.length
    ? (deviations.reduce((sum, value) => sum + value, 0) / deviations.length).toFixed(1)
    : '—'
  return [
    { label: '在册工作面', value: total.value },
    { label: '衔接冲突', value: rows.value.filter((row) => row['台账状态'] === '衔接冲突').length },
    { label: '待批准版本', value: rows.value.filter((row) => row['待批准']).length },
    { label: '平均偏差(月)', value: average },
  ]
})

const formTitle = computed(() => ({
  create: '登记接续计划（台账 + V1 草稿版）',
  version: `另出新版：${formValues.value.__label ?? ''}（原版保留，批准后生效）`,
  progress: `登记实际进度：${formValues.value.__label ?? ''}（回写台账）`,
}[activeForm.value] ?? ''))

const formFields = computed(() => ({
  create: createFields,
  version: versionFields,
  progress: progressFields,
}[activeForm.value] ?? []))

function resetFilters() {
  filters.value = { keyword: '', mode: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openForm(kind: string, row?: Row) {
  errorMessage.value = ''
  noticeMessage.value = ''
  activeForm.value = kind
  if (row) {
    selectedId.value = row.id
  }
  formValues.value = kind === 'create'
    ? { 进度口径: '开完工口径' }
    : { __label: String(row?.['工作面编号'] ?? ''), 进度口径: '开完工口径' }
}

async function submitForm() {
  const kind = activeForm.value
  const values = { ...formValues.value }
  delete values.__label
  const target = kind === 'create' ? ENDPOINT : `${ENDPOINT}/${selectedId.value}/${kind === 'version' ? 'versions' : 'progress'}`
  await postAction(target, values)
}

async function approve(row: Row) {
  await postAction(`${ENDPOINT}/${row.id}/actions`, { action: '批准版本' })
}

async function postAction(url: string, values: Record<string, unknown>) {
  errorMessage.value = ''
  noticeMessage.value = ''
  try {
    const response = await request(url, { method: 'POST', body: JSON.stringify({ values }) })
    const payload = await response.json()
    if (!payload.ok) {
      throw new Error(payload.message || '操作未生效')
    }
    noticeMessage.value = payload.message
    activeForm.value = ''
    await reload()
    if (selectedId.value) {
      await showDetail({ id: selectedId.value })
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '采掘接续操作失败'
  }
}

async function showDetail(row: Row) {
  errorMessage.value = ''
  selectedId.value = row.id
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('版本记录读取失败')
    }
    detail.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版本记录读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(
    Object.fromEntries(Object.entries(filters.value).filter(([, value]) => value)),
  ).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('接续计划台账读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '接续计划台账读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.form-panel,
.detail-panel {
  margin: 12px 0;
  padding: 12px 16px;
  border: 1px solid var(--line, #d8dee9);
  border-radius: 8px;
  background: var(--panel, #fff);
}

.form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px 16px;
  margin-bottom: 12px;
}

tr.selected td {
  background: rgba(64, 128, 255, 0.08);
}

.notice-text {
  color: #1a7f37;
}
</style>
