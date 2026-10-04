<template>
  <section class="page" data-module="succession">
    <header class="page-head">
      <div>
        <h2>采掘接续计划</h2>
        <p class="page-desc">一个采煤工作面一条接续记录；计划调整另出新版、原版保留，实际进度登记后回写台账，衔接关系以版本里的先后为准。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记接续计划</button>
        <button class="btn" type="button" @click="openCaliber">调整接续口径</button>
        <button class="btn" type="button" @click="runBackfill">存量回填</button>
        <button class="btn" type="button" @click="exportRows">导出接续台账</button>
      </div>
    </header>

    <div class="caliber-bar">
      <span>当前接续口径：<strong>{{ caliber['当前口径'] || '—' }}</strong></span>
      <span v-if="caliber['调整时间']" class="caliber-meta">{{ caliber['调整人'] }} · {{ caliber['调整时间'] }} 调整</span>
      <span v-if="caliber['说明']" class="caliber-meta">{{ caliber['说明'] }}</span>
    </div>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>工作面</span>
        <input v-model="filters.keyword" placeholder="按编号或名称检索" />
      </label>
      <label class="filter-item">
        <span>进度状态</span>
        <select v-model="filters.status">
          <option value="">全部</option>
          <option v-for="item in statuses" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th>工作面编号</th>
          <th>工作面名称</th>
          <th>接续方式</th>
          <th>计划开工</th>
          <th>计划完工</th>
          <th>前续工作面</th>
          <th>后续工作面</th>
          <th>当前版本</th>
          <th>版本状态</th>
          <th>实际开工</th>
          <th>实际完工</th>
          <th>偏差(月)</th>
          <th>进度状态</th>
          <th>衔接冲突</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td>{{ row['工作面编号'] }}</td>
          <td>{{ row['工作面名称'] }}</td>
          <td>{{ row['接续方式'] ?? '—' }}</td>
          <td>{{ row['计划开工月份'] ?? '—' }}</td>
          <td>{{ row['计划完工月份'] ?? '—' }}</td>
          <td>{{ row['前续工作面'] ?? '—' }}</td>
          <td>{{ row['后续工作面'] ?? '—' }}</td>
          <td>{{ row['当前版本号'] ?? '—' }}</td>
          <td><span :class="['tag', row['版本状态'] === '草稿' ? 'tag-draft' : '']">{{ row['版本状态'] }}</span></td>
          <td>{{ row['实际开工月份'] ?? '—' }}</td>
          <td>{{ row['实际完工月份'] ?? '—' }}</td>
          <td :class="{ lag: Number(row['偏差月数']) > 0 }">{{ formatDeviation(row['偏差月数']) }}</td>
          <td>{{ row.status }}</td>
          <td><span v-if="row['衔接冲突']" class="tag tag-conflict">冲突</span><template v-else>—</template></td>
          <td class="row-actions">
            <button class="link" type="button" @click="openVersions(row)">版本记录</button>
            <button class="link" type="button" @click="openProgress(row)">登记进度</button>
            <button class="link" type="button" @click="openRevise(row)">另出新版</button>
            <button v-if="row['版本状态'] === '草稿'" class="link" type="button" @click="approve(row)">批复</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="15" class="empty-state">暂无采掘接续数据，可先登记接续计划或执行存量回填</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条采掘接续记录</span>
      <span v-if="notice" class="notice-text">{{ notice }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <div v-if="panel" class="modal-mask" @click.self="closePanel">
      <div class="modal-panel">
        <header class="modal-head">
          <h3>{{ panelTitle }}</h3>
          <button class="link" type="button" @click="closePanel">关闭</button>
        </header>

        <form v-if="panel === 'create'" class="modal-form" @submit.prevent="submitCreate">
          <label class="filter-item"><span>工作面编号</span><input v-model="createForm['工作面编号']" placeholder="如 CMI-3201" /></label>
          <label class="filter-item"><span>工作面名称</span><input v-model="createForm['工作面名称']" placeholder="如 3201 综采工作面" /></label>
          <label class="filter-item"><span>所在采区</span><input v-model="createForm['所在采区']" placeholder="如 三采区" /></label>
          <label class="filter-item">
            <span>接续方式</span>
            <select v-model="createForm['接续方式']">
              <option value="">请选择</option>
              <option v-for="item in methods" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="filter-item"><span>计划开工月份</span><input v-model="createForm['计划开工月份']" type="month" /></label>
          <label class="filter-item"><span>计划完工月份</span><input v-model="createForm['计划完工月份']" type="month" /></label>
          <label class="filter-item"><span>前续工作面</span><input v-model="createForm['前续工作面']" placeholder="可留空" /></label>
          <label class="filter-item"><span>后续工作面</span><input v-model="createForm['后续工作面']" placeholder="可留空" /></label>
          <div class="modal-actions">
            <button class="btn primary" type="submit">登记并生成 V1</button>
          </div>
        </form>

        <form v-else-if="panel === 'revise'" class="modal-form" @submit.prevent="submitRevise">
          <p class="modal-desc">以 {{ activeRow?.['工作面编号'] }} 当前版本 {{ activeRow?.['当前版本号'] }} 为底另出新版，原版保留；没填的字段沿用当前版本。</p>
          <label class="filter-item">
            <span>接续方式</span>
            <select v-model="reviseForm['接续方式']">
              <option v-for="item in methods" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="filter-item"><span>计划开工月份</span><input v-model="reviseForm['计划开工月份']" type="month" /></label>
          <label class="filter-item"><span>计划完工月份</span><input v-model="reviseForm['计划完工月份']" type="month" /></label>
          <label class="filter-item"><span>前续工作面</span><input v-model="reviseForm['前续工作面']" /></label>
          <label class="filter-item"><span>后续工作面</span><input v-model="reviseForm['后续工作面']" /></label>
          <label class="filter-item"><span>调整说明</span><input v-model="reviseForm['调整说明']" placeholder="本次调整原因" /></label>
          <div class="modal-actions">
            <button class="btn primary" type="submit">另出新版</button>
          </div>
        </form>

        <form v-else-if="panel === 'progress'" class="modal-form" @submit.prevent="submitProgress">
          <p class="modal-desc">登记 {{ activeRow?.['工作面编号'] }} 的实际进度，结果回写接续计划台账；实际衔接与当前版本不一致时只记冲突，衔接关系仍以版本里的先后为准。</p>
          <label class="filter-item"><span>实际开工月份</span><input v-model="progressForm['实际开工月份']" type="month" /></label>
          <label class="filter-item"><span>实际完工月份</span><input v-model="progressForm['实际完工月份']" type="month" /></label>
          <label class="filter-item"><span>实际衔接工作面</span><input v-model="progressForm['实际衔接工作面']" placeholder="设备实际转入的工作面，可留空" /></label>
          <label class="filter-item"><span>备注</span><input v-model="progressForm['备注']" placeholder="可留空" /></label>
          <div class="modal-actions">
            <button class="btn primary" type="submit">登记并回写台账</button>
          </div>
        </form>

        <form v-else-if="panel === 'caliber'" class="modal-form" @submit.prevent="submitCaliber">
          <p class="modal-desc">口径调整后按新口径重算台账偏差；历史版本仍按当时的进度口径保留。</p>
          <label class="filter-item">
            <span>接续口径</span>
            <select v-model="caliberForm['口径']">
              <option v-for="item in caliberOptions" :key="item" :value="item">{{ item }}</option>
            </select>
          </label>
          <label class="filter-item"><span>调整说明</span><input v-model="caliberForm['说明']" placeholder="本次口径调整原因" /></label>
          <div class="modal-actions">
            <button class="btn primary" type="submit">调整并重算偏差</button>
          </div>
        </form>

        <div v-else-if="panel === 'versions'" class="modal-detail">
          <p class="modal-desc">{{ activeRow?.['工作面编号'] }} 的版本链：历史版本按当时的进度口径保留，当前版本即台账读到的版本。</p>
          <table class="data-table">
            <thead>
              <tr>
                <th>版本号</th>
                <th>状态</th>
                <th>接续方式</th>
                <th>计划开工</th>
                <th>计划完工</th>
                <th>前续</th>
                <th>后续</th>
                <th>进度口径</th>
                <th>偏差(月)</th>
                <th>调整说明</th>
                <th>登记</th>
                <th>批复</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="version in versions" :key="String(version.id)">
                <td>{{ version['版本号'] }}<span v-if="version['是否当前版本']" class="tag tag-current">当前</span></td>
                <td>{{ version['版本状态'] }}</td>
                <td>{{ version['接续方式'] ?? '—' }}</td>
                <td>{{ version['计划开工月份'] ?? '—' }}</td>
                <td>{{ version['计划完工月份'] ?? '—' }}</td>
                <td>{{ version['前续工作面'] ?? '—' }}</td>
                <td>{{ version['后续工作面'] ?? '—' }}</td>
                <td>{{ version['进度口径'] ?? '—' }}</td>
                <td :class="{ lag: Number(version['偏差月数']) > 0 }">{{ formatDeviation(version['偏差月数']) }}</td>
                <td>{{ version['调整说明'] ?? '—' }}</td>
                <td>{{ version['登记人'] }} · {{ version['登记时间'] }}</td>
                <td>{{ version['批复人'] ? `${version['批复人']} · ${version['批复时间']}` : '—' }}</td>
              </tr>
            </tbody>
          </table>
          <h4 class="modal-subhead">进度登记记录</h4>
          <table class="data-table">
            <thead>
              <tr>
                <th>登记时间</th>
                <th>实际开工</th>
                <th>实际完工</th>
                <th>实际衔接</th>
                <th>衔接冲突</th>
                <th>登记人</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in progressList" :key="String(item.id)">
                <td>{{ item['登记时间'] }}</td>
                <td>{{ item['实际开工月份'] ?? '—' }}</td>
                <td>{{ item['实际完工月份'] ?? '—' }}</td>
                <td>{{ item['实际衔接工作面'] ?? '—' }}</td>
                <td><span v-if="item['衔接冲突']" class="tag tag-conflict">冲突</span><template v-else>—</template></td>
                <td>{{ item['登记人'] }}</td>
                <td>{{ item['备注'] ?? '—' }}</td>
              </tr>
              <tr v-if="!progressList.length">
                <td colspan="7" class="empty-state">尚未登记实际进度</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/succession'
const statuses = ['未开工', '回采中', '已完工']
const methods = ['顺序接续', '跳采接续', '延伸接续', '新面接续']

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const notice = ref('')
const filters = ref({ keyword: '', status: '' })
const caliber = ref<Row>({})
const caliberOptions = ref<string[]>([])

const panel = ref('')
const panelTitle = ref('')
const activeRow = ref<Row | null>(null)
const versions = ref<Row[]>([])
const progressList = ref<Row[]>([])

const createForm = ref<Record<string, string>>({})
const reviseForm = ref<Record<string, string>>({})
const progressForm = ref<Record<string, string>>({})
const caliberForm = ref<Record<string, string>>({})

const stats = computed(() => [
  { label: '在册工作面', value: total.value },
  { label: '回采中', value: rows.value.filter((row) => row.status === '回采中').length },
  { label: '已完工', value: rows.value.filter((row) => row.status === '已完工').length },
  { label: '衔接冲突', value: rows.value.filter((row) => row['衔接冲突']).length },
])

function formatDeviation(value: Row[string]) {
  if (value === null || value === undefined || value === '') return '—'
  const months = Number(value)
  if (months > 0) return `+${months} 滞后`
  if (months < 0) return `${months} 提前`
  return '0'
}

function resetFilters() {
  filters.value = { keyword: '', status: '' }
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function closePanel() {
  panel.value = ''
  activeRow.value = null
}

function openPanel(name: string, title: string, row: Row | null = null) {
  activeRow.value = row
  panelTitle.value = title
  panel.value = name
}

function openCreate() {
  createForm.value = { 工作面编号: '', 工作面名称: '', 所在采区: '', 接续方式: '', 计划开工月份: '', 计划完工月份: '', 前续工作面: '', 后续工作面: '' }
  openPanel('create', '登记接续计划')
}

function openRevise(row: Row) {
  reviseForm.value = {
    接续方式: String(row['接续方式'] ?? ''),
    计划开工月份: String(row['计划开工月份'] ?? ''),
    计划完工月份: String(row['计划完工月份'] ?? ''),
    前续工作面: String(row['前续工作面'] ?? ''),
    后续工作面: String(row['后续工作面'] ?? ''),
    调整说明: '',
  }
  openPanel('revise', `另出新版 · ${row['工作面编号']}`, row)
}

function openProgress(row: Row) {
  progressForm.value = { 实际开工月份: '', 实际完工月份: '', 实际衔接工作面: '', 备注: '' }
  openPanel('progress', `登记实际进度 · ${row['工作面编号']}`, row)
}

function openCaliber() {
  caliberForm.value = { 口径: String(caliber.value['当前口径'] ?? ''), 说明: '' }
  openPanel('caliber', '调整接续口径')
}

async function openVersions(row: Row) {
  openPanel('versions', `版本记录 · ${row['工作面编号']}`, row)
  try {
    const [versionResp, detailResp] = await Promise.all([
      request(`${ENDPOINT}/${row.id}/versions`),
      request(`${ENDPOINT}/${row.id}`),
    ])
    const versionPayload = await versionResp.json()
    versions.value = versionPayload.items ?? []
    const detail = await detailResp.json()
    progressList.value = detail['进度记录'] ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版本记录读取失败'
  }
}

async function post(path: string, values: Record<string, string>) {
  const response = await request(path, { method: 'POST', body: JSON.stringify({ values }) })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.message || payload.detail || '操作未生效，请稍后重试')
  }
  return payload
}

async function runAction(action: () => Promise<{ message?: string }>) {
  errorMessage.value = ''
  notice.value = ''
  try {
    const payload = await action()
    notice.value = payload.message ?? '操作已完成'
    closePanel()
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

function submitCreate() {
  return runAction(() => post(ENDPOINT, createForm.value))
}

function submitRevise() {
  const row = activeRow.value
  if (!row) return
  return runAction(() => post(`${ENDPOINT}/${row.id}/revise`, reviseForm.value))
}

function submitProgress() {
  const row = activeRow.value
  if (!row) return
  return runAction(() => post(`${ENDPOINT}/${row.id}/progress`, progressForm.value))
}

function submitCaliber() {
  return runAction(() => post(`${ENDPOINT}/caliber`, caliberForm.value))
}

function approve(row: Row) {
  return runAction(() => post(`${ENDPOINT}/${row.id}/approve`, {}))
}

function runBackfill() {
  return runAction(() => post(`${ENDPOINT}/backfill`, {}))
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) query.set('keyword', filters.value.keyword)
  if (filters.value.status) query.set('status', filters.value.status)
  query.set('size', '200')
  try {
    const [listResp, caliberResp] = await Promise.all([
      request(`${ENDPOINT}?${query}`),
      request(`${ENDPOINT}/caliber`),
    ])
    if (!listResp.ok) throw new Error('接续计划台账读取失败')
    const payload = await listResp.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
    if (caliberResp.ok) {
      const caliberPayload = await caliberResp.json()
      caliber.value = caliberPayload
      caliberOptions.value = caliberPayload['可选口径'] ?? []
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '接续计划台账读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.caliber-bar {
  display: flex;
  gap: 16px;
  align-items: center;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 12px;
  font-size: 13px;
}
.caliber-meta { color: var(--muted); font-size: 12px; }
.tag {
  display: inline-block;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0 6px;
  font-size: 12px;
  line-height: 18px;
}
.tag-draft { color: #b45309; border-color: #f0c78a; background: #fffaeb; }
.tag-conflict { color: #b42318; border-color: #f1b0a8; background: #fef3f2; }
.tag-current { color: #1f6feb; border-color: #9ec2f5; background: #eff6ff; margin-left: 4px; }
.lag { color: #b42318; }
.notice-text { color: #067647; }
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.4);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 8vh;
  z-index: 10;
}
.modal-panel {
  background: #fff;
  border-radius: 8px;
  padding: 16px 20px;
  width: 920px;
  max-width: 94vw;
  max-height: 80vh;
  overflow: auto;
}
.modal-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.modal-head h3 { margin: 0; font-size: 15px; }
.modal-desc { color: var(--muted); font-size: 12px; margin: 4px 0 12px; }
.modal-form { display: flex; flex-wrap: wrap; gap: 10px; align-items: flex-end; }
.modal-form .filter-item { min-width: 200px; }
.modal-form input, .modal-form select { display: block; width: 100%; padding: 6px 8px; border: 1px solid var(--border); border-radius: 6px; }
.modal-actions { width: 100%; display: flex; justify-content: flex-end; margin-top: 4px; }
.modal-subhead { font-size: 13px; margin: 16px 0 8px; }
</style>
