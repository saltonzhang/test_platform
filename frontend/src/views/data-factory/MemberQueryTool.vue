<template>
  <el-drawer v-model="visible" title="查询用户信息" size="min(680px, 92vw)">
    <div class="data-factory-detail member-query-tool">
      <div class="data-factory-detail-head">
        <span class="data-factory-icon blue">
          <el-icon><UserFilled /></el-icon>
        </span>
        <div>
          <h3>查询用户信息</h3>
          <p>选择环境包并输入邮箱或昵称，查询会员基础信息。</p>
        </div>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="member-query-form">
        <el-form-item label="环境包" prop="environment_package">
          <el-select v-model="form.environment_package" clearable placeholder="请选择环境包" style="width: 100%">
            <el-option v-for="pkg in environmentPackages" :key="pkg.id" :label="pkg.name" :value="pkg.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="邮箱或昵称" prop="keyword">
          <el-input v-model="form.keyword" clearable placeholder="请输入邮箱或昵称" />
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
          <el-descriptions-item label="UUID">
            <span class="member-query-copyable" title="双击复制" @dblclick.prevent="copyText(result.uid, 'UUID')">{{ result.uid }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="ID Number">
            <span class="member-query-copyable" title="双击复制" @dblclick.prevent="copyText(result.cpf, 'ID Number')">{{ result.cpf }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="ID">
            <span class="member-query-copyable" title="双击复制" @dblclick.prevent="copyText(result.member_id, 'ID')">{{ result.member_id }}</span>
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
import { reactive, ref, watch } from 'vue'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { RefreshLeft, Search, UserFilled } from '@element-plus/icons-vue'
import * as api from '@/api'
import type { EnvironmentPackage, MemberQueryResult } from '@/types'

const visible = defineModel<boolean>({ default: false })
const props = defineProps<{ environmentPackages: EnvironmentPackage[] }>()
const emit = defineEmits<{ executed: [] }>()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const searched = ref(false)
const result = ref<MemberQueryResult | null>(null)
const form = reactive<{ environment_package: number | null; keyword: string }>({
  environment_package: null,
  keyword: '',
})

const rules: FormRules = {
  environment_package: [{ required: true, message: '请选择环境包' }],
  keyword: [{ required: true, message: '请输入邮箱或昵称' }],
}

function resetForm() {
  form.environment_package = null
  form.keyword = ''
  result.value = null
  searched.value = false
  formRef.value?.clearValidate()
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

watch(() => props.environmentPackages, (packages) => {
  if (form.environment_package && !packages.some((item) => item.id === form.environment_package)) form.environment_package = null
  if (!form.environment_package && packages.length) form.environment_package = packages[0].id
}, { immediate: true })

watch(visible, (isVisible) => {
  if (isVisible) {
    resetForm()
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
  submitting.value = true
  searched.value = false
  try {
    const response = await api.queryMemberInfo({ environment_package: form.environment_package, keyword: form.keyword.trim() })
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
