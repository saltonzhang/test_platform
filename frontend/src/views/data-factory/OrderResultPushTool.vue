<template>
  <el-drawer v-model="visible" title="订单结果推送" size="min(760px, 94vw)">
    <div class="data-factory-detail">
      <div class="data-factory-detail-head">
        <span class="data-factory-icon green">
          <el-icon><Promotion /></el-icon>
        </span>
        <div>
          <h3>订单结果推送</h3>
          <p>根据 event_id 生成消息 key，并按已授权的操作推送订单结果、回滚结算、取消或回滚取消。</p>
        </div>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <div class="order-result-form">
          <el-form-item label="certainty" prop="certainty">
            <el-input v-model="form.certainty" />
          </el-form-item>
          <el-form-item label="product" prop="product">
            <el-input v-model="form.product" />
          </el-form-item>
          <el-form-item class="wide" label="event_id" prop="event_id">
            <el-input v-model="form.event_id" placeholder="例如 sr:match:72827258 或 pn2tgn3bkz5viycygy" />
          </el-form-item>
          <el-form-item label="market id" prop="market_id">
            <el-input v-model="form.market_id" />
          </el-form-item>
          <el-form-item label="specifiers">
            <el-input v-model="form.specifiers" placeholder="例如 total=1.5，可为空" />
          </el-form-item>
          <el-form-item label="outcome id" prop="outcome_id">
            <el-input v-model="form.outcome_id" placeholder="例如 70 或 geya" />
          </el-form-item>
          <el-form-item label="result" prop="result">
            <el-input v-model="form.result" />
          </el-form-item>
          <el-form-item label="void_factor" prop="void_factor">
            <el-input v-model="form.void_factor" />
          </el-form-item>
          <el-form-item label="timestamp（毫秒）" prop="timestamp">
            <el-input-number v-model="form.timestamp" :min="1" :precision="0" controls-position="right" style="width:100%" />
          </el-form-item>
          <el-form-item label="start_time（可空）">
            <el-input v-model="form.start_time" placeholder="例如 1783955756714" />
          </el-form-item>
          <el-form-item label="end_time（可空）">
            <el-input v-model="form.end_time" placeholder="例如 1783960403911" />
          </el-form-item>
        </div>
      </el-form>

      <div class="order-result-actions">
        <el-button v-if="hasPermission('data_factory.order_result_push')" type="primary" :loading="submitting" :disabled="isSubmitting" @click="submit">
          <el-icon><Promotion /></el-icon>
          推送订单结果
        </el-button>
        <el-button v-if="hasPermission('data_factory.rollback_settlement')" type="warning" :loading="rollbackSubmitting" :disabled="isSubmitting" @click="rollback">
          <el-icon><RefreshLeft /></el-icon>
          回滚结算
        </el-button>
        <el-button v-if="hasPermission('data_factory.bet_cancel')" type="danger" :loading="cancelSubmitting" :disabled="isSubmitting" @click="cancel">
          取消
        </el-button>
        <el-button v-if="hasPermission('data_factory.rollback_bet_cancel')" type="success" :loading="rollbackCancelSubmitting" :disabled="isSubmitting" @click="rollbackCancel">
          <el-icon><RefreshLeft /></el-icon>
          回滚取消
        </el-button>
      </div>

      <el-result
        v-if="response"
        icon="success"
        :title="resultTitle"
        :sub-title="`HTTP ${response.status_code} · ${response.message}`"
      >
        <template #extra>
          <div class="order-result-response">
            <el-descriptions :column="1" border>
              <el-descriptions-item label="实际 event ID">{{ response.event_id }}</el-descriptions-item>
              <el-descriptions-item label="消息 Key">{{ response.key }}</el-descriptions-item>
              <el-descriptions-item v-if="response.outcome_id" label="实际 outcome ID">{{ response.outcome_id }}</el-descriptions-item>
              <el-descriptions-item label="时间戳">{{ response.timestamp }}</el-descriptions-item>
            </el-descriptions>
            <pre>{{ response.response || '接口未返回响应正文' }}</pre>
          </div>
        </template>
      </el-result>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Promotion, RefreshLeft } from '@element-plus/icons-vue'
import { hasPermission } from '@/auth'
import * as api from '@/api'
import type { OrderResultPushResult } from '@/types'

const visible = defineModel<boolean>({ default: false })
const emit = defineEmits<{ executed: [] }>()
const submitting = ref(false)
const rollbackSubmitting = ref(false)
const cancelSubmitting = ref(false)
const rollbackCancelSubmitting = ref(false)
const formRef = ref<FormInstance>()
const response = ref<OrderResultPushResult>()
const lastAction = ref<'push' | 'rollback' | 'cancel' | 'rollbackCancel'>('push')
const isSubmitting = computed(() => submitting.value || rollbackSubmitting.value || cancelSubmitting.value || rollbackCancelSubmitting.value)
const resultTitle = computed(() => ({
  push: '推送成功',
  rollback: '回滚成功',
  cancel: '取消成功',
  rollbackCancel: '回滚取消成功',
}[lastAction.value]))
const form = reactive({
  certainty: '2',
  product: '1',
  event_id: '',
  market_id: '',
  specifiers: '',
  outcome_id: '',
  result: '0',
  void_factor: '0',
  timestamp: Date.now(),
  start_time: '',
  end_time: '',
})
const rules: FormRules = {
  certainty: [{ required: true, message: '请输入 certainty' }],
  product: [{ required: true, message: '请输入 product' }],
  event_id: [{ required: true, message: '请输入 event_id' }],
  market_id: [{ required: true, message: '请输入 market id' }],
  outcome_id: [{ required: true, message: '请输入 outcome id' }],
  result: [{ required: true, message: '请输入 result' }],
  void_factor: [{ required: true, message: '请输入 void_factor' }],
  timestamp: [{ required: true, message: '请输入毫秒时间戳' }],
}

watch(visible, isVisible => {
  if (isVisible) {
    form.timestamp = Date.now()
    form.start_time = ''
    form.end_time = ''
    response.value = undefined
    lastAction.value = 'push'
  }
})

async function validateFields(fields: string[]) {
  if (!formRef.value) return false
  formRef.value.clearValidate(['certainty', 'outcome_id', 'result', 'void_factor', 'timestamp'])
  return formRef.value.validateField(fields).then(() => true).catch(() => false)
}

async function submit() {
  if (!hasPermission('data_factory.order_result_push')) return
  if (!await formRef.value?.validate().catch(() => false)) return
  submitting.value = true
  try {
    const result = await api.pushOrderResult({
      certainty: form.certainty,
      product: form.product,
      event_id: form.event_id,
      market_id: form.market_id,
      specifiers: form.specifiers,
      outcome_id: form.outcome_id,
      result: form.result,
      void_factor: form.void_factor,
      timestamp: form.timestamp,
    })
    response.value = result.data
    lastAction.value = 'push'
    emit('executed')
    ElMessage.success('订单结果推送成功')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    submitting.value = false
  }
}

async function rollback() {
  if (!hasPermission('data_factory.rollback_settlement')) return
  if (!await validateFields(['product', 'event_id', 'market_id', 'timestamp'])) return
  rollbackSubmitting.value = true
  try {
    const result = await api.rollbackSettlement({
      product: form.product,
      event_id: form.event_id,
      market_id: form.market_id,
      specifiers: form.specifiers,
      timestamp: form.timestamp,
    })
    response.value = result.data
    lastAction.value = 'rollback'
    emit('executed')
    ElMessage.success('回滚结算提交成功')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    rollbackSubmitting.value = false
  }
}

async function cancel() {
  if (!hasPermission('data_factory.bet_cancel')) return
  if (!await validateFields(['product', 'event_id', 'market_id'])) return
  cancelSubmitting.value = true
  try {
    const timestamp = Number(form.timestamp)
    const result = await api.cancelBet({
      product: form.product,
      event_id: form.event_id,
      market_id: form.market_id,
      specifiers: form.specifiers,
      start_time: form.start_time.trim(),
      end_time: form.end_time.trim(),
      timestamp: Number.isFinite(timestamp) && timestamp > 0 ? timestamp : undefined,
    })
    response.value = result.data
    lastAction.value = 'cancel'
    emit('executed')
    ElMessage.success('取消提交成功')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    cancelSubmitting.value = false
  }
}

async function rollbackCancel() {
  if (!hasPermission('data_factory.rollback_bet_cancel')) return
  if (!await validateFields(['product', 'event_id', 'market_id'])) return
  rollbackCancelSubmitting.value = true
  try {
    const timestamp = Number(form.timestamp)
    const result = await api.rollbackBetCancel({
      product: form.product,
      event_id: form.event_id,
      market_id: form.market_id,
      specifiers: form.specifiers,
      start_time: form.start_time.trim(),
      end_time: form.end_time.trim(),
      timestamp: Number.isFinite(timestamp) && timestamp > 0 ? timestamp : undefined,
    })
    response.value = result.data
    lastAction.value = 'rollbackCancel'
    emit('executed')
    ElMessage.success('回滚取消提交成功')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    rollbackCancelSubmitting.value = false
  }
}
</script>
