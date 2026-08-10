<template>
  <el-drawer v-model="visible" title="查询用户信息" size="min(680px, 92vw)">
    <div class="data-factory-detail member-query-tool">
      <div class="data-factory-detail-head">
        <span class="data-factory-icon blue">
          <el-icon><UserFilled /></el-icon>
        </span>
        <div>
          <h3>查询用户信息</h3>
          <p>选择环境并输入邮箱，查询会员基础信息。</p>
        </div>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="member-query-form">
        <el-form-item label="运行环境" prop="environment">
          <el-select v-model="form.environment" clearable placeholder="请选择运行环境" style="width: 100%">
            <el-option
              v-for="env in environmentOptions"
              :key="env.id"
              :label="env.name"
              :value="env.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" clearable placeholder="请输入邮箱" />
        </el-form-item>
      </el-form>

      <div class="member-query-actions">
        <el-button type="primary" :loading="submitting" @click="submit">
          <el-icon><Search /></el-icon>
          查询
        </el-button>
        <el-button :disabled="submitting" @click="resetForm">
          <el-icon><RefreshLeft /></el-icon>
          重置
        </el-button>
      </div>

      <section v-if="result" class="member-query-result">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="环境">
            <span class="member-query-copyable" title="双击复制" @dblclick.prevent="copyText(result.environment_name, '环境')">{{ result.environment_name }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="邮箱">
            <span class="member-query-copyable" title="双击复制" @dblclick.prevent="copyText(result.email, '邮箱')">{{ result.email }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="UID">
            <span class="member-query-copyable" title="双击复制" @dblclick.prevent="copyText(result.uid, 'UID')">{{ result.uid }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="CPF">
            <span class="member-query-copyable" title="双击复制" @dblclick.prevent="copyText(result.cpf, 'CPF')">{{ result.cpf }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="Member ID">
            <span class="member-query-copyable" title="双击复制" @dblclick.prevent="copyText(result.member_id, 'Member ID')">{{ result.member_id }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="昵称">
            <span class="member-query-copyable" title="双击复制" @dblclick.prevent="copyText(result.nickname, '昵称')">{{ result.nickname }}</span>
          </el-descriptions-item>
        </el-descriptions>
      </section>
      <el-empty v-else-if="searched" description="暂无查询结果" />
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { RefreshLeft, Search, UserFilled } from '@element-plus/icons-vue'
import * as api from '@/api'
import type { Environment, MemberQueryResult } from '@/types'

const visible = defineModel<boolean>({ default: false })
const props = defineProps<{ environments: Environment[] }>()
const emit = defineEmits<{ executed: [] }>()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const searched = ref(false)
const result = ref<MemberQueryResult | null>(null)
const preferredEnvironmentNames = ['前端测试环境', '前台测试环境', '测试环境']
const shouldApplyDefaultEnvironment = ref(true)
const form = reactive<{ environment: number | null; email: string }>({
  environment: null,
  email: '',
})

const environmentOptions = computed(() => props.environments)
const rules: FormRules = {
  environment: [{ required: true, message: '请选择运行环境' }],
  email: [
    { required: true, message: '请输入邮箱' },
    { type: 'email', message: '邮箱格式不正确' },
  ],
}

function resetForm() {
  shouldApplyDefaultEnvironment.value = true
  form.environment = null
  form.email = ''
  result.value = null
  searched.value = false
  formRef.value?.clearValidate()
}

function getDefaultEnvironmentId(options: Environment[]) {
  for (const preferredName of preferredEnvironmentNames) {
    const matched = options.find((item) => item.name === preferredName)
    if (matched) {
      return matched.id
    }
  }
  return options[0]?.id ?? null
}

function syncDefaultEnvironment(options = environmentOptions.value) {
  if (!options.length) {
    return
  }
  if (form.environment && options.some((item) => item.id === form.environment)) {
    shouldApplyDefaultEnvironment.value = false
    return
  }
  if (!form.environment && !shouldApplyDefaultEnvironment.value) {
    return
  }
  form.environment = getDefaultEnvironmentId(options)
  shouldApplyDefaultEnvironment.value = false
}

async function copyText(text: string, label: string) {
  const value = String(text || '').trim()
  if (!value) {
    ElMessage.warning(`暂无可复制的${label}`)
    return
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = value
      textarea.setAttribute('readonly', 'true')
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      const copied = document.execCommand('copy')
      document.body.removeChild(textarea)
      if (!copied) {
        throw new Error('复制失败')
      }
    }
    ElMessage.success(`${label}已复制`)
  } catch (error) {
    ElMessage.error((error as Error).message || '复制失败')
  }
}

watch(environmentOptions, (options) => {
  if (form.environment && !options.some((item) => item.id === form.environment)) {
    form.environment = null
    shouldApplyDefaultEnvironment.value = true
  }
  syncDefaultEnvironment(options)
}, { immediate: true })

watch(visible, (isVisible) => {
  if (isVisible) {
    resetForm()
    syncDefaultEnvironment()
  }
})

async function submit() {
  if (!(await formRef.value?.validate().catch(() => false))) {
    return
  }
  if (!form.environment) {
    ElMessage.warning('请选择运行环境')
    return
  }
  submitting.value = true
  searched.value = false
  try {
    const response = await api.queryMemberInfo({
      environment: form.environment,
      email: form.email.trim(),
    })
    result.value = response.data
    searched.value = true
    emit('executed')
    ElMessage.success('查询成功')
  } catch (error) {
    result.value = null
    searched.value = true
    ElMessage.error((error as Error).message)
  } finally {
    submitting.value = false
  }
}
</script>
