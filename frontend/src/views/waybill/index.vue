<template>
  <section class="page" data-module="waybill">
    <header class="page-head">
      <div>
        <h2>运单管理管理</h2>
        <p class="page-desc">维护冷链运单，围绕运单号、关联订单、承运车辆、司机姓名做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记冷链运单</button>
        <button class="btn" type="button" @click="exportRows">导出运单管理清单</button>
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
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <template v-if="actionsFor(row).length">
              <button
                v-for="action in actionsFor(row)"
                :key="action"
                class="link"
                type="button"
                :disabled="busyId === String(row.id)"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="action-muted">已结束流转</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无运单管理数据，可先登记冷链运单</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条运单管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>
interface ActionResponse {
  ok: boolean
  message: string
}

const ENDPOINT = '/api/waybill'
const columns = ["运单号", "关联订单", "承运车辆", "司机姓名", "装车时间", "卸货时间", "运单状态"]

// 状态流转约束（与后端一致）：待装车可确认装车/作废；运输中可签收/作废；终态不再给入口
const ACTIONS_BY_STATUS: Record<string, string[]> = {
  "待装车": ["确认装车", "作废运单"],
  "运输中": ["签收运单", "作废运单"],
  "已签收": [],
  "已作废": [],
}

const stats = [{"label": "在途运单", "value": 0}, {"label": "待签收运单", "value": 0}, {"label": "异常运单", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const busyId = ref('')

function statusOf(row: Row): string {
  return String(row["运单状态"] ?? row.status ?? "")
}

function actionsFor(row: Row): string[] {
  return ACTIONS_BY_STATUS[statusOf(row)] ?? []
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '冷链运单登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  // 请求未返回前禁用该行入口，连续点两次签收时第二次不会再发请求
  const rowId = String(row.id)
  if (busyId.value === rowId) return
  errorMessage.value = ''
  busyId.value = rowId
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    if (!response.ok) {
      throw new Error('运单管理动作未生效，请稍后重试')
    }
    const result = (await response.json()) as ActionResponse
    if (!result.ok) {
      // 被后端流转规则拦下：直接展示后端给出的原因，不推进本地状态
      errorMessage.value = result.message
      return
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '运单管理操作失败'
  } finally {
    busyId.value = ''
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('冷链运单列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '运单管理列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.action-muted {
  color: var(--muted, #64748b);
  font-size: 12px;
}

.link:disabled {
  color: var(--muted, #64748b);
  cursor: not-allowed;
  opacity: 0.6;
}

.row-actions .link + .link {
  margin-left: 12px;
}
</style>
