<template>
  <el-drawer v-model="visible" title="用户状态激活" size="min(700px, 92vw)">
    <div class="data-factory-detail">
      <div class="data-factory-detail-head">
        <span class="data-factory-icon green">
          <el-icon><CircleCheckFilled /></el-icon>
        </span>
        <div>
          <h3>用户状态激活</h3>
          <p>选择环境包并输入邮箱激活用户状态。</p>
        </div>
      </div>

      <el-alert
        title="系统会使用所选环境包中的后台配置执行。"
        type="info"
        :closable="false"
        show-icon
      />

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="member-query-form">
        <el-form-item label="环境包" prop="environment_package">
          <el-select v-model="form.environment_package" clearable placeholder="请选择环境包" style="width: 100%">
            <el-option v-for="pkg in environmentPackages" :key="pkg.id" :label="pkg.name" :value="pkg.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="会员邮箱" prop="email">
          <el-input
            v-model="form.email"
            clearable
            placeholder="请输入会员邮箱"
          />
        </el-form-item>
      </el-form>

      <div class="member-query-actions">
        <el-button type="primary" :loading="submitting" @click="submit">
          <el-icon><CircleCheckFilled /></el-icon>
          激活用户状态
        </el-button>
        <el-button :disabled="submitting" @click="resetForm">
          <el-icon><RefreshLeft /></el-icon>
          重置
        </el-button>
      </div>

      <section v-if="result" class="member-query-result">
        <el-alert
          :title="result.message"
          type="success"
          :closable="false"
          show-icon
        />
        <el-descriptions :column="1" border>
          <el-descriptions-item label="后台环境">{{ result.environment_name }}</el-descriptions-item>
          <el-descriptions-item label="Member ID">{{ result.member_id }}</el-descriptions-item>
          <el-descriptions-item label="影响行数">{{ result.affected_rows }}</el-descriptions-item>
          <el-descriptions-item label="执行结果">{{ result.status === 'passed' ? '已完成' : result.status }}</el-descriptions-item>
        </el-descriptions>
      </section>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { CircleCheckFilled, RefreshLeft } from '@element-plus/icons-vue'
import * as api from '@/api'
import type { EnvironmentPackage, MemberStatusActivateResult } from '@/types'

const visible = defineModel<boolean>({ default: false })
const props = defineProps<{ environmentPackages: EnvironmentPackage[] }>()
const emit = defineEmits<{ executed: [] }>()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const result = ref<MemberStatusActivateResult | null>(null)
const form = reactive<{ environment_package: number | null; email: string }>({
  environment_package: null,
  email: '',
})

const rules: FormRules = {
  environment_package: [{ required: true, message: '请选择环境包' }],
  email: [{ required: true, message: '请输入会员邮箱' }, { type: 'email', message: '邮箱格式不正确' }],
}

function resetForm() {
  form.environment_package = null
  form.email = ''
  result.value = null
  formRef.value?.clearValidate()
}

watch(() => props.environmentPackages, (packages) => {
  if (form.environment_package && !packages.some(item => item.id === form.environment_package)) form.environment_package = null
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
  const environmentName = props.environmentPackages.find(item => item.id === form.environment_package)?.name || String(form.environment_package)
  try {
    await ElMessageBox.confirm(
      `确认在「${environmentName}」环境下激活邮箱 ${form.email} 的用户状态吗？`,
      '确认用户状态激活',
      { type: 'warning', confirmButtonText: '确认执行' },
    )
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error((error as Error).message)
    }
    return
  }

  submitting.value = true
  try {
    const response = await api.activateMemberStatus({
      environment_package: form.environment_package,
      email: form.email.trim(),
    })
    result.value = response.data
    emit('executed')
    ElMessage.success('用户状态激活成功')
  } catch (error) {
    result.value = null
    ElMessage.error((error as Error).message)
  } finally {
    submitting.value = false
  }
}
</script>
