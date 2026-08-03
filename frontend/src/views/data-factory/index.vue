<template>
  <section class="surface data-factory-page">
    <div class="section-head bordered">
      <div>
        <h3>数据工厂</h3>
        <p>数据生成与处理工作区</p>
      </div>
      <el-button @click="openHistory">
        <el-icon><Document /></el-icon>
        操作记录
      </el-button>
    </div>

    <div class="data-factory-grid">
      <button
        v-if="hasPermission('data_factory.account_balance')"
        class="data-factory-card"
        type="button"
        @click="accountBalanceVisible = true"
      >
        <span class="data-factory-icon blue"><el-icon><WalletFilled /></el-icon></span>
        <strong>账户余额</strong>
        <small>按邮箱查询会员并创建、审批加款单据</small>
        <b>可用</b>
      </button>

      <button
        v-if="hasPermission('data_factory.account_add')"
        class="data-factory-card"
        type="button"
        @click="accountAddVisible = true"
      >
        <span class="data-factory-icon amber"><el-icon><CirclePlusFilled /></el-icon></span>
        <strong>账户添加</strong>
        <small>分别选择前台环境和后台环境，再填写邮箱、数量、金额和系统密码</small>
        <b>可用</b>
      </button>

      <button
        v-if="hasPermission('data_factory.order_result_push')"
        class="data-factory-card"
        type="button"
        @click="orderResultPushVisible = true"
      >
        <span class="data-factory-icon green"><el-icon><Promotion /></el-icon></span>
        <strong>订单结果推送</strong>
        <small>生成消息 Key 并推送订单结算结果</small>
        <b>可用</b>
      </button>

      <article
        v-for="item in pendingTools"
        :key="item.name"
        class="data-factory-card disabled"
      >
        <span :class="['data-factory-icon', item.tone]">
          <el-icon><component :is="item.icon" /></el-icon>
        </span>
        <strong>{{ item.name }}</strong>
        <small>{{ item.summary }}</small>
        <b>待接入</b>
      </article>
    </div>
  </section>

  <AccountBalanceTool v-model="accountBalanceVisible" :environments="environments" @executed="loadHistory" />
  <AccountAddTool v-model="accountAddVisible" :environments="environments" @executed="loadHistory" />
  <OrderResultPushTool v-model="orderResultPushVisible" @executed="loadHistory" />

  <el-drawer v-model="historyVisible" title="数据工厂操作记录" size="min(940px, 94vw)">
    <el-table v-loading="historyLoading" :data="history" empty-text="暂无操作记录">
      <el-table-column prop="tool_name" label="工具名" width="120" />
      <el-table-column prop="operator_name" label="操作人" width="110" />
      <el-table-column label="执行内容" min-width="430">
        <template #default="{ row }">
          <el-tooltip :content="formatExecutionContent(row.execution_content)" placement="top" :show-after="300">
            <span>{{ formatExecutionContent(row.execution_content) }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column label="操作时间" width="170">
        <template #default="{ row }">{{ formatTime(row.executed_at) }}</template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-model:current-page="historyQuery.page"
      v-model:page-size="historyQuery.pageSize"
      :page-sizes="[10, 50, 100]"
      :total="historyTotal"
      layout="total, sizes, prev, pager, next"
      @current-change="loadHistory"
      @size-change="changeHistoryPageSize"
    />
  </el-drawer>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Brush, CirclePlusFilled, Connection, Document, Promotion, Tickets, WalletFilled } from '@element-plus/icons-vue'
import { hasPermission } from '@/auth'
import * as api from '@/api'
import dayjs from 'dayjs'
import type { DataFactoryExecution, Environment } from '@/types'
import AccountAddTool from './AccountAddTool.vue'
import AccountBalanceTool from './AccountBalanceTool.vue'
import OrderResultPushTool from './OrderResultPushTool.vue'

const pendingTools = [
  { name: '订单数据', summary: '构造订单、支付、退款场景', icon: Tickets, tone: 'green' },
  { name: '接口参数', summary: '生成接口请求参数模板', icon: Connection, tone: 'amber' },
  { name: '数据清理', summary: '整理重复、空值和脏数据', icon: Brush, tone: 'red' },
]

const environments = ref<Environment[]>([])
const accountBalanceVisible = ref(false)
const accountAddVisible = ref(false)
const orderResultPushVisible = ref(false)
const historyVisible = ref(false)
const historyLoading = ref(false)
const history = ref<DataFactoryExecution[]>([])
const historyTotal = ref(0)
const historyQuery = reactive({ page: 1, pageSize: 10 })

async function loadHistory() {
  historyLoading.value = true
  try {
    const response = await api.getDataFactoryExecutions(historyQuery)
    history.value = response.data.list
    historyTotal.value = response.data.total
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    historyLoading.value = false
  }
}

async function openHistory() {
  historyQuery.page = 1
  historyVisible.value = true
  await loadHistory()
}

function changeHistoryPageSize() {
  historyQuery.page = 1
  void loadHistory()
}

function formatExecutionContent(content: Record<string, string>) {
  return Object.entries(content)
    .map(([key, value]) => `${key}：${value}`)
    .join('；')
}

function formatTime(value: string) {
  return dayjs(value).format('YYYY-MM-DD HH:mm:ss')
}

onMounted(async () => {
  try {
    const response = await api.getEnvironments()
    environments.value = Array.isArray(response) ? response : response.data
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
})
</script>
