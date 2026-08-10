<template>
  <el-dialog v-model="visible" title="环境账号设置" width="min(680px, 94vw)" destroy-on-close @open="load">
    <div v-loading="loading" class="environment-account-settings">
      <div class="environment-account-add">
        <el-select
          v-model="selectedEnvironmentId"
          filterable
          clearable
          placeholder="选择环境"
          :disabled="loading || !availableEnvironments.length"
        >
          <el-option
            v-for="environment in availableEnvironments"
            :key="environment.id"
            :label="environment.name"
            :value="environment.id"
          />
        </el-select>
        <el-button type="primary" :icon="Plus" :disabled="!selectedEnvironmentId" @click="addEnvironment">添加环境</el-button>
      </div>

      <el-empty v-if="!loading && !accounts.length" description="暂无已添加环境" />
      <el-form v-else label-position="top" class="environment-account-list">
        <div class="environment-account-column-head">
          <span>环境</span>
          <span>环境账号</span>
          <span aria-hidden="true"></span>
        </div>
        <div v-for="item in accounts" :key="item.environment_id" class="environment-account-row">
          <span class="environment-account-name" :title="item.environment_name">{{ item.environment_name }}</span>
          <el-form-item class="environment-account-input">
            <el-input
              v-model="item.account"
              autocomplete="username"
              clearable
              maxlength="100"
              placeholder="请输入账号"
            />
          </el-form-item>
          <el-tooltip content="移除环境账号" placement="top">
            <el-button circle text type="danger" :icon="Delete" :disabled="saving" aria-label="移除环境账号" @click="removeEnvironment(item)" />
          </el-tooltip>
        </div>
      </el-form>
    </div>
    <template #footer>
      <el-button :disabled="saving" @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="saving" :disabled="loading" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Delete, Plus } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api'
import type { EnvironmentAccount, EnvironmentAccountOption } from '@/types'

const visible = defineModel<boolean>({ default: false })
const accounts = ref<EnvironmentAccount[]>([])
const environments = ref<EnvironmentAccountOption[]>([])
const selectedEnvironmentId = ref<number>()
const loading = ref(false)
const saving = ref(false)
const persistedEnvironmentIds = ref<number[]>([])
const removedEnvironmentIds = ref<number[]>([])

const availableEnvironments = computed(() => {
  const configuredIds = new Set(accounts.value.map(item => item.environment_id))
  return environments.value.filter(environment => !configuredIds.has(environment.id))
})

async function load() {
  loading.value = true
  try {
    const response = await api.getMyEnvironmentAccounts()
    accounts.value = response.data.accounts.map(item => ({ ...item }))
    environments.value = response.data.environments.map(item => ({ ...item }))
    persistedEnvironmentIds.value = accounts.value.map(item => item.environment_id)
    removedEnvironmentIds.value = []
    selectedEnvironmentId.value = undefined
  } catch (error) {
    accounts.value = []
    environments.value = []
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

function addEnvironment() {
  const environment = environments.value.find(item => item.id === selectedEnvironmentId.value)
  if (!environment) return
  accounts.value.push({ environment_id: environment.id, environment_name: environment.name, account: '' })
  removedEnvironmentIds.value = removedEnvironmentIds.value.filter(id => id !== environment.id)
  selectedEnvironmentId.value = undefined
}

async function removeEnvironment(item: EnvironmentAccount) {
  try {
    await ElMessageBox.confirm(`确定移除环境“${item.environment_name}”的账号配置吗？`, '移除环境账号', {
      type: 'warning',
      confirmButtonText: '移除',
    })
  } catch {
    return
  }
  if (persistedEnvironmentIds.value.includes(item.environment_id)) {
    removedEnvironmentIds.value.push(item.environment_id)
  }
  accounts.value = accounts.value.filter(account => account.environment_id !== item.environment_id)
}

async function save() {
  if (accounts.value.some(item => !item.account.trim())) {
    ElMessage.warning('请填写已添加环境的账号')
    return
  }
  saving.value = true
  try {
    const response = await api.saveMyEnvironmentAccounts(
      [
        ...accounts.value.map(item => ({ environment_id: item.environment_id, account: item.account.trim() })),
        ...removedEnvironmentIds.value.map(environment_id => ({ environment_id, account: '' })),
      ],
    )
    accounts.value = response.data.accounts.map(item => ({ ...item }))
    environments.value = response.data.environments.map(item => ({ ...item }))
    persistedEnvironmentIds.value = accounts.value.map(item => item.environment_id)
    removedEnvironmentIds.value = []
    ElMessage.success('环境账号已保存')
    visible.value = false
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.environment-account-settings { min-height: 180px; }
.environment-account-add { display: flex; gap: 12px; margin-bottom: 20px; }
.environment-account-add :deep(.el-select) { flex: 1; min-width: 0; }
.environment-account-list { border-top: 1px solid #eaecf0; }
.environment-account-column-head { display: grid; grid-template-columns: minmax(120px, 0.45fr) minmax(0, 1fr) 32px; column-gap: 16px; color: #667085; font-size: 13px; font-weight: 600; padding: 11px 4px; }
.environment-account-row { display: grid; grid-template-columns: minmax(120px, 0.45fr) minmax(0, 1fr) 32px; align-items: center; column-gap: 16px; border-bottom: 1px solid #eaecf0; padding: 12px 4px; }
.environment-account-row:last-child { border-bottom: 0; }
.environment-account-name { overflow: hidden; color: #344054; font-weight: 600; line-height: 32px; text-overflow: ellipsis; white-space: nowrap; }
.environment-account-input { margin-bottom: 0; }

@media (max-width: 560px) {
  .environment-account-add { align-items: stretch; flex-direction: column; }
  .environment-account-column-head { grid-template-columns: minmax(88px, 0.4fr) minmax(0, 1fr) 32px; column-gap: 8px; }
  .environment-account-row { grid-template-columns: minmax(88px, 0.4fr) minmax(0, 1fr) 32px; column-gap: 8px; }
}
</style>
