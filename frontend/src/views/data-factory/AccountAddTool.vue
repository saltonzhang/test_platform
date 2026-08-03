<template>
  <el-drawer v-model="visible" title="账户添加" size="min(820px, 94vw)">
    <div class="data-factory-detail account-add-tool">
      <div class="data-factory-detail-head">
        <span class="data-factory-icon amber">
          <el-icon><CirclePlusFilled /></el-icon>
        </span>
        <div>
          <h3>账户添加</h3>
          <p>前台环境取 base_url，后台环境取 login_url；请分别选择两个环境后再执行。</p>
        </div>
      </div>

      <el-alert
        title="请分别选择前台环境和后台环境，后端会按两个环境分别取地址执行。"
        type="info"
        :closable="false"
        show-icon
      />

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="account-add-form">
        <section class="account-add-section">
          <div class="account-add-section-head">
            <strong>运行环境</strong>
            <span>前台环境与后台环境分开选择</span>
          </div>

          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
              <el-form-item label="前台运行环境" prop="frontend_environment">
                <el-select v-model="form.frontend_environment" clearable placeholder="请选择前台环境" style="width: 100%">
                  <el-option
                    v-for="env in environmentOptions"
                    :key="env.id"
                    :label="env.name"
                    :value="env.id"
                  />
                </el-select>
              </el-form-item>
            </el-col>

            <el-col :xs="24" :sm="12">
              <el-form-item label="后台运行环境" prop="backend_environment">
                <el-select v-model="form.backend_environment" clearable placeholder="请选择后台环境" style="width: 100%">
                  <el-option
                    v-for="env in environmentOptions"
                    :key="env.id"
                    :label="env.name"
                    :value="env.id"
                  />
                </el-select>
              </el-form-item>
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

          <el-row :gutter="16">
            <el-col :xs="24" :sm="12">
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
            </el-col>
            <el-col :xs="24" :sm="12">
              <el-form-item label="系统密码" prop="login_password">
                <el-input v-model="form.login_password" type="password" show-password autocomplete="off" />
              </el-form-item>
            </el-col>
          </el-row>
        </section>
      </el-form>

      <div class="account-add-actions">
        <el-button type="primary" :loading="submitting" @click="submit">执行账户添加</el-button>
        <el-button :disabled="submitting" @click="resetForm">重置</el-button>
      </div>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { CirclePlusFilled } from '@element-plus/icons-vue'
import * as api from '@/api'
import type { Environment } from '@/types'

const visible = defineModel<boolean>({ default: false })
const props = defineProps<{ environments: Environment[] }>()
const emit = defineEmits<{ executed: [] }>()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = reactive<{
  frontend_environment: number | null
  backend_environment: number | null
  email: string
  quantity: number
  amount: number | null
  login_password: string
}>({
  frontend_environment: null,
  backend_environment: null,
  email: '',
  quantity: 1,
  amount: null,
  login_password: '',
})

const environmentOptions = computed(() => props.environments)

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
  frontend_environment: [{ required: true, message: '请选择前台运行环境' }],
  backend_environment: [{ required: true, message: '请选择后台运行环境' }],
  email: [{ validator: validateEmail, trigger: 'blur' }],
  quantity: [{ required: true, message: '请输入数量' }, { validator: validatePositiveInteger, trigger: 'change' }],
  amount: [{ validator: validateAmount, trigger: 'change' }],
  login_password: [{ required: true, message: '请输入系统密码' }],
}

function syncSelections() {
  if (form.frontend_environment && !environmentOptions.value.some((item) => item.id === form.frontend_environment)) {
    form.frontend_environment = null
  }
  if (form.backend_environment && !environmentOptions.value.some((item) => item.id === form.backend_environment)) {
    form.backend_environment = null
  }
}

function resetForm() {
  form.frontend_environment = null
  form.backend_environment = null
  form.email = ''
  form.quantity = 1
  form.amount = null
  form.login_password = ''
}

watch(environmentOptions, syncSelections, { immediate: true })
watch(visible, (isVisible) => {
  if (isVisible) {
    resetForm()
  }
})

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) {
    return
  }
  if (!form.frontend_environment || !form.backend_environment) {
    ElMessage.warning('请选择前台环境和后台环境')
    return
  }
  const frontendEnvironmentId = form.frontend_environment
  const backendEnvironmentId = form.backend_environment
  try {
    await ElMessageBox.confirm(
      `确认使用前台环境「${environmentOptions.value.find((item) => item.id === frontendEnvironmentId)?.name || frontendEnvironmentId}」和后台环境「${environmentOptions.value.find((item) => item.id === backendEnvironmentId)?.name || backendEnvironmentId}」执行账户添加吗？`,
      '确认账户添加',
      { type: 'warning', confirmButtonText: '确认执行' },
    )
    submitting.value = true
    const result = await api.executeAccountAdd({
      frontend_environment: frontendEnvironmentId,
      backend_environment: backendEnvironmentId,
      email: form.email,
      quantity: form.quantity,
      amount: form.amount,
      login_password: form.login_password,
    })
    form.login_password = ''
    visible.value = false
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
