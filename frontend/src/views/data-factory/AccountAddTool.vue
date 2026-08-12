<template>
  <el-drawer v-model="visible" title="账户添加" size="min(820px, 94vw)">
    <div class="data-factory-detail account-add-tool">
      <div class="data-factory-detail-head">
        <span class="data-factory-icon amber">
          <el-icon><CirclePlusFilled /></el-icon>
        </span>
        <div>
          <h3>账户添加</h3>
          <p>注册默认密码：Test1234!，账号可在本页面和操作记录查看。</p>
        </div>
      </div>

      <el-alert
        title="请选择环境包，后端会自动读取其中的前台和后台配置执行。"
        type="info"
        :closable="false"
        show-icon
      />

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="account-add-form">
        <section class="account-add-section">
          <div class="account-add-section-head">
            <strong>运行环境</strong>
            <span>按环境名称识别前台和后台配置</span>
          </div>

          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item label="环境包" prop="environment_package">
                <el-select v-model="form.environment_package" clearable placeholder="请选择环境包" style="width: 100%">
                  <el-option v-for="pkg in usablePackages" :key="pkg.id" :label="pkg.name" :value="pkg.id" />
                </el-select>
              </el-form-item>
            </el-col>

            <el-col :xs="24" :sm="12">
              <el-form-item label="配置预览"><span>{{ selectedPackageSummary }}</span></el-form-item>
            </el-col>
          </el-row>
        </section>

        <section class="account-add-section">
          <div class="account-add-section-head">
            <strong>账户参数</strong>
            <span>邮箱可选，数量用于控制注册账号数</span>
          </div>

          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item label="会员邮箱（可选）" prop="email">
                <el-input v-model="form.email" placeholder="请输入会员邮箱" />
              </el-form-item>
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="数量" prop="quantity">
                <el-input-number
                  v-model="form.quantity"
                  :min="1"
                  :precision="0"
                  controls-position="right"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
          </el-row>

          <el-form-item label="邀请码（可选）" prop="referral_code">
            <el-input v-model="form.referral_code" placeholder="填写后，新账号将作为该邀请码的下级注册" />
          </el-form-item>

          <el-form-item label="金额" prop="amount">
            <el-input-number
              v-model="form.amount"
              :min="0"
              :precision="2"
              :step="1"
              controls-position="right"
              style="width: 100%"
            />
          </el-form-item>
        </section>
      </el-form>

      <div class="account-add-actions">
        <el-button type="primary" :loading="submitting" @click="submit">执行账户添加</el-button>
        <el-button :disabled="submitting" @click="resetForm">重置</el-button>
      </div>

      <section v-if="resultVisible" class="account-add-result">
        <div class="account-add-result-head">
          <div>
            <strong>注册账号结果</strong>
            <span v-if="resultState === 'running'">后台正在执行，可手动刷新结果查看最新账号。</span>
            <span v-else-if="resultState === 'passed'">默认密码：Test1234!，以下为本次生成的账号。</span>
            <span v-else>执行失败，请查看上方提示信息。</span>
          </div>
          <div class="account-add-result-head-actions">
            <el-tag :type="resultTagType" effect="plain">{{ resultStateLabel }}</el-tag>
            <el-button
              type="primary"
              link
              :loading="refreshing"
              :disabled="!currentExecutionId || refreshing"
              @click="refreshResultByExecutionId"
            >
              刷新结果
            </el-button>
          </div>
        </div>

        <div v-if="generatedEmails.length" class="account-add-result-list">
          <div v-for="(account, index) in generatedEmails" :key="`${account}-${index}`" class="account-add-result-item">
            <span class="account-add-result-index">{{ index + 1 }}</span>
            <span class="account-add-result-email">{{ account }}</span>
          </div>
        </div>
        <el-empty v-else-if="resultState === 'running'" description="账号生成后会显示在这里" />
        <el-empty v-else description="暂无可展示账号" />
      </section>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { CirclePlusFilled } from '@element-plus/icons-vue'
import * as api from '@/api'
import type { EnvironmentPackage } from '@/types'

const visible = defineModel<boolean>({ default: false })
const props = defineProps<{ environmentPackages: EnvironmentPackage[] }>()
const emit = defineEmits<{ executed: [] }>()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const resultVisible = ref(false)
const resultState = ref<'idle' | 'running' | 'passed' | 'failed'>('idle')
const generatedEmails = ref<string[]>([])
const currentExecutionId = ref<number | null>(null)
const refreshing = ref(false)
const form = reactive<{
  environment_package: number | null
  email: string
  referral_code: string
  quantity: number
  amount: number | null
}>({
  environment_package: null,
  email: '',
  referral_code: '',
  quantity: 1,
  amount: null,
})

const isFrontendEnvironment = (name: string) => name.includes('前台') || name.includes('前端')
const usablePackages = computed(() => props.environmentPackages)
const selectedPackageSummary = computed(() => { const pkg = usablePackages.value.find(item => item.id === form.environment_package); if (!pkg) return '请选择环境包'; const frontend = pkg.environments.find(env => isFrontendEnvironment(env.name)); const backend = pkg.environments.find(env => env.name.includes('后台')); return `前台：${frontend?.name || '未配置'}；后台：${backend?.name || '未配置'}` })
const resultStateLabel = computed(() => ({
  idle: '待执行',
  running: '执行中',
  passed: '已完成',
  failed: '执行失败',
}[resultState.value]))
const resultTagType = computed(() => ({
  idle: 'info',
  running: 'warning',
  passed: 'success',
  failed: 'danger',
}[resultState.value]))

const validatePositiveInteger = (_rule: unknown, value: number, callback: (error?: Error) => void) => {
  if (!Number.isInteger(value) || value < 1) {
    callback(new Error('数量必须为正整数'))
    return
  }
  callback()
}

const validateAmount = (_rule: unknown, value: number | null, callback: (error?: Error) => void) => {
  if (value === null || value === undefined) {
    callback()
    return
  }
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
    callback(new Error('金额不能小于 0'))
    return
  }
  callback()
}

const validateEmail = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  if (!value) {
    callback()
    return
  }
  const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
  if (!emailPattern.test(value)) {
    callback(new Error('邮箱格式不正确'))
    return
  }
  callback()
}

const rules: FormRules = {
  environment_package: [{ required: true, message: '请选择环境包' }],
  email: [{ validator: validateEmail, trigger: 'blur' }],
  quantity: [{ required: true, message: '请输入数量' }, { validator: validatePositiveInteger, trigger: 'change' }],
  amount: [{ validator: validateAmount, trigger: 'change' }],
}

function resetForm() {
  form.environment_package = null
  form.email = ''
  form.referral_code = ''
  form.quantity = 1
  form.amount = null
  resetResultPanel()
}

function resetResultPanel() {
  resultVisible.value = false
  resultState.value = 'idle'
  generatedEmails.value = []
  currentExecutionId.value = null
}

function extractGeneratedEmails(content: Record<string, string>) {
  const rawEmails = content['生成邮箱'] || content['会员邮箱'] || ''
  return String(rawEmails)
    .split('、')
    .map(item => item.trim())
    .filter(Boolean)
}

async function refreshResultByExecutionId() {
  if (!currentExecutionId.value) return
  refreshing.value = true
  try {
    const response = await api.getDataFactoryExecutions({ page: 1, pageSize: 100 })
    const row = response.data.list.find(item => item.id === currentExecutionId.value)
    if (!row) return
    const content = row.execution_content || {}
    const state = String(content['执行结果'] || '')
    const emails = extractGeneratedEmails(content)
    if (emails.length) {
      generatedEmails.value = emails
    }
    if (state === '执行中') {
      resultState.value = 'running'
      return
    }
    resultState.value = state === '执行失败' ? 'failed' : 'passed'
    if (!generatedEmails.value.length && content['会员邮箱']) {
      generatedEmails.value = [content['会员邮箱']]
    }
  } catch {
    // 保持手动刷新即可
  } finally {
    refreshing.value = false
  }
}

watch(usablePackages, packages => { if (packages.length && !packages.some(item => item.id === form.environment_package)) form.environment_package = packages[0].id }, { immediate: true })
watch(visible, (isVisible) => {
  if (isVisible) {
    resetForm()
  } else {
    resetResultPanel()
  }
})

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) {
    return
  }
  if (!form.environment_package) {
    ElMessage.warning('请选择环境包')
    return
  }
  try {
    const selectedPackage = usablePackages.value.find(item => item.id === form.environment_package)
    await ElMessageBox.confirm(
      `确认使用环境包「${selectedPackage?.name || form.environment_package}」执行账户添加吗？`,
      '确认账户添加',
      { type: 'warning', confirmButtonText: '确认执行' },
    )
    submitting.value = true
    const result = await api.executeAccountAdd({
      environment_package: form.environment_package,
      email: form.email,
      referral_code: form.referral_code,
      quantity: form.quantity,
      amount: form.amount,
    })
    if (result.data.execution_id) {
      currentExecutionId.value = result.data.execution_id
      resultVisible.value = true
      resultState.value = 'running'
      generatedEmails.value = []
      void refreshResultByExecutionId()
    } else {
      resultVisible.value = true
      resultState.value = 'passed'
      generatedEmails.value = result.data.email ? [result.data.email] : []
    }
    emit('executed')
    ElMessage.success(result.data.environment_name ? `账户添加已提交，后台执行中：${result.data.environment_name}` : '账户添加已提交，后台执行中')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error((error as Error).message)
    }
  } finally {
    submitting.value = false
  }
}

</script>
