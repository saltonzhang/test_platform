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

    <div class="data-factory-groups">
      <section
        v-if="hasAnyPermission(['data_factory.account_balance','data_factory.account_add','data_factory.member_status_activate','data_factory.member_query'])"
        class="data-factory-group"
      >
        <div class="data-factory-group-head">
          <div>
            <h4>用户中心</h4>
            
          </div>
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
        v-if="hasPermission('data_factory.member_status_activate')"
        class="data-factory-card"
        type="button"
        @click="memberStatusActivateVisible = true"
      >
        <span class="data-factory-icon green"><el-icon><CircleCheckFilled /></el-icon></span>
        <strong>用户状态激活</strong>
        <small>输入 member_id 激活用户状态，环境字段仅作预留</small>
        <b>可用</b>
      </button>

      <button
        v-if="hasPermission('data_factory.member_query')"
        class="data-factory-card"
        type="button"
        @click="memberQueryVisible = true"
      >
        <span class="data-factory-icon blue"><el-icon><UserFilled /></el-icon></span>
        <strong>查询用户信息</strong>
        <small>选择运行环境并按邮箱查询 UID、CPF、Member ID 和昵称</small>
        <b>可用</b>
      </button>

        </div>
      </section>

      <section
        v-if="hasAnyPermission(['data_factory.order_result_push','data_factory.rollback_settlement','data_factory.bet_cancel','data_factory.rollback_bet_cancel'])"
        class="data-factory-group"
      >
        <div class="data-factory-group-head">
          <div>
            <h4>赛事活动</h4>
            
          </div>
        </div>
        <div class="data-factory-grid">
          <button
            class="data-factory-card"
            type="button"
            @click="orderResultPushVisible = true"
          >
            <span class="data-factory-icon green"><el-icon><Promotion /></el-icon></span>
            <strong>订单结果推送</strong>
            <small>推送订单结果，或执行回滚结算、取消和回滚取消</small>
            <b>可用</b>
          </button>
        </div>
      </section>

    </div>
  </section>

  <AccountBalanceTool v-model="accountBalanceVisible" :environment-packages="environmentPackages" @executed="loadHistory" />
  <AccountAddTool v-model="accountAddVisible" :environment-packages="environmentPackages" @executed="loadHistory" />
  <MemberStatusActivateTool v-model="memberStatusActivateVisible" :environment-packages="environmentPackages" @executed="loadHistory" />
  <MemberQueryTool v-model="memberQueryVisible" :environment-packages="environmentPackages" @executed="loadHistory" />
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
import { CircleCheckFilled, CirclePlusFilled, Document, Promotion, UserFilled, WalletFilled } from '@element-plus/icons-vue'
import { hasPermission } from '@/auth'
import * as api from '@/api'
import dayjs from 'dayjs'
import type { DataFactoryExecution, Environment, EnvironmentPackage } from '@/types'
import AccountAddTool from './AccountAddTool.vue'
import AccountBalanceTool from './AccountBalanceTool.vue'
import MemberStatusActivateTool from './MemberStatusActivateTool.vue'
import MemberQueryTool from './MemberQueryTool.vue'
import OrderResultPushTool from './OrderResultPushTool.vue'

const environments = ref<Environment[]>([])
const environmentPackages = ref<EnvironmentPackage[]>([])
const accountBalanceVisible = ref(false)
const accountAddVisible = ref(false)
const memberStatusActivateVisible = ref(false)
const memberQueryVisible = ref(false)
const orderResultPushVisible = ref(false)
const historyVisible = ref(false)
const historyLoading = ref(false)
const history = ref<DataFactoryExecution[]>([])
const historyTotal = ref(0)
const historyQuery = reactive({ page: 1, pageSize: 10 })

function hasAnyPermission(codes: string[]) {
  return codes.some(hasPermission)
}

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
    const response = await api.getDataFactoryEnvironments()
    environments.value = response.data
    try {
      const packageResponse = await api.getDataFactoryEnvironmentPackages()
      environmentPackages.value = Array.isArray(packageResponse) ? packageResponse : packageResponse.data
    } catch {
      environmentPackages.value = []
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
})
</script>

<style scoped>
.data-factory-groups { display: grid; gap: 30px; margin-top: 20px; }
.data-factory-group + .data-factory-group { border-top: 1px solid #eaecf0; padding-top: 26px; }
.data-factory-group-head { display: flex; align-items: center; justify-content: space-between; }
.data-factory-group-head h4 { margin: 0 0 4px; color: #667085; font-size: 13px; font-weight: 600; }
.data-factory-group-head p { margin: 0; color: #98a2b3; font-size: 11px; }
.data-factory-group .data-factory-grid { margin-top: 16px; }
</style>
