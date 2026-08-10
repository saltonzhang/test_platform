<template>
  <el-drawer v-model="visible" title="用户状态激活" size="min(700px, 92vw)">
    <div class="data-factory-detail">
      <div class="data-factory-detail-head">
        <span class="data-factory-icon green">
          <el-icon><CircleCheckFilled /></el-icon>
        </span>
        <div>
          <h3>用户状态激活</h3>
          <p>输入 member_id 激活用户状态。运行环境仅作预留，不参与当前数据库选择。</p>
        </div>
      </div>

      <el-alert
        title="当前环境字段仅保留给后续按环境切库使用，现阶段仍连接默认数据工厂数据库。"
        type="info"
        :closable="false"
        show-icon
      />

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
        <el-form-item label="Member ID" prop="member_id">
          <el-input
            v-model="form.member_id"
            clearable
            placeholder="请输入 member_id"
            inputmode="numeric"
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
          <el-descriptions-item label="运行环境（预留）">{{ result.environment_name }}</el-descriptions-item>
          <el-descriptions-item label="Member ID">{{ result.member_id }}</el-descriptions-item>
          <el-descriptions-item label="影响行数">{{ result.affected_rows }}</el-descriptions-item>
          <el-descriptions-item label="执行结果">{{ result.status === 'passed' ? '已完成' : result.status }}</el-descriptions-item>
        </el-descriptions>
      </section>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { CircleCheckFilled, RefreshLeft } from '@element-plus/icons-vue'
import * as api from '@/api'
import type { Environment, MemberStatusActivateResult } from '@/types'

const visible = defineModel<boolean>({ default: false })
const props = defineProps<{ environments: Environment[] }>()
const emit = defineEmits<{ executed: [] }>()

const formRef = ref<FormInstance>()
const submitting = ref(false)
const result = ref<MemberStatusActivateResult | null>(null)
const form = reactive<{ environment: number | null; member_id: string }>({
  environment: null,
  member_id: '',
})

const environmentOptions = computed(() => props.environments)
const rules: FormRules = {
  environment: [{ required: true, message: '请选择运行环境' }],
  member_id: [
    { required: true, message: '请输入 member_id' },
    { pattern: /^\d+$/, message: 'member_id 必须是数字' },
  ],
}

function resetForm() {
  form.environment = null
  form.member_id = ''
  result.value = null
  formRef.value?.clearValidate()
}

watch(environmentOptions, (options) => {
  if (form.environment && !options.some((item) => item.id === form.environment)) {
    form.environment = null
  }
  if (!form.environment && options.length) {
    form.environment = options[0].id
  }
}, { immediate: true })

watch(visible, (isVisible) => {
  if (isVisible) {
    resetForm()
    if (environmentOptions.value.length) {
      form.environment = environmentOptions.value[0].id
    }
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
  const environmentName = environmentOptions.value.find((item) => item.id === form.environment)?.name || String(form.environment)
  try {
    await ElMessageBox.confirm(
      `确认在「${environmentName}」环境下激活 member_id ${form.member_id} 的用户状态吗？`,
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
      environment: form.environment,
      member_id: form.member_id.trim(),
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
