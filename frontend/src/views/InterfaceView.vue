<template>
  <div>
    <section class="surface interface-list">
      <div class="interface-toolbar">
        <el-input v-model="query.keyword" clearable placeholder="搜索请求 URL" @input="filterInterfaces" />
        <el-select v-model="query.module_name" multiple collapse-tags collapse-tags-tooltip clearable placeholder="业务模块" @change="filterInterfaces">
          <el-option v-for="item in BUSINESS_MODULES" :key="item" :label="item" :value="item" />
        </el-select>
        <span>共 {{ total }} 个接口</span>
        <div class="interface-actions"><el-button type="success" @click="batchDialog = true"><el-icon><Upload /></el-icon>批量录入</el-button><el-button type="primary" @click="openForm()"><el-icon><Plus /></el-icon>新建接口</el-button></div>
      </div>
      <el-table v-loading="loading" :data="interfaces" empty-text="暂无接口">
        <el-table-column prop="name" label="接口名称" min-width="170" />
        <el-table-column label="方法" width="90"><template #default="{ row }"><el-tag :type="methodType(row.method)" effect="plain">{{ row.method }}</el-tag></template></el-table-column>
        <el-table-column prop="path" label="请求路径" min-width="230"><template #default="{ row }"><code>{{ row.path }}</code></template></el-table-column>
        <el-table-column prop="module_name" label="业务模块" width="110" />
        <el-table-column prop="api_type" label="接口类型" width="100" />
        <el-table-column label="关联标记" width="100"><template #default="{ row }"><el-tag v-if="row.reference_enabled" type="warning" effect="plain">已关联</el-tag><span v-else class="muted-text">未设置</span></template></el-table-column>
        <el-table-column label="关联接口" min-width="160" show-overflow-tooltip><template #default="{ row }">{{ row.reference_interface_name || '-' }}</template></el-table-column>
        <el-table-column label="任务可执行" width="105"><template #default="{ row }"><el-switch v-model="row.can_execute_in_task" @change="toggleExecutable(row)" /></template></el-table-column>
        <el-table-column label="更新时间" min-width="150"><template #default="{ row }">{{ formatTime(row.updated_at) }}</template></el-table-column>
        <el-table-column label="操作" width="170" fixed="right"><template #default="{ row }"><el-button size="small" plain type="primary" @click="openForm(row)">编辑</el-button><el-button size="small" plain type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
      </el-table>
      <el-pagination v-model:current-page="query.page" v-model:page-size="query.pageSize" :page-sizes="pageSizes" :total="total" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="changePageSize" />
    </section>

    <el-dialog v-model="dialog" :title="form.id ? '编辑接口' : '新建接口'" width="720">
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="接口名称" prop="name"><el-input v-model="form.name" /></el-form-item>
        <el-row :gutter="16"><el-col :span="8"><el-form-item label="请求方法" prop="method"><el-select v-model="form.method"><el-option v-for="item in methods" :key="item" :label="item" :value="item" /></el-select></el-form-item></el-col><el-col :span="16"><el-form-item label="请求路径" prop="path"><el-input v-model="form.path" placeholder="/api/example/" /></el-form-item></el-col></el-row>
        <el-row :gutter="16"><el-col :span="12"><el-form-item label="业务模块" prop="module_name"><el-select v-model="form.module_name" placeholder="请选择业务模块" style="width:100%" @change="applyModuleTokenHeader"><el-option v-for="item in BUSINESS_MODULES" :key="item" :label="item" :value="item" /></el-select></el-form-item></el-col><el-col :span="12"><el-form-item label="接口类型" prop="api_type"><el-select v-model="form.api_type" disabled style="width:100%"><el-option label="系统录入" value="系统录入" /></el-select></el-form-item></el-col></el-row>
        <el-form-item label="关联标记"><el-checkbox v-model="form.reference_enabled">启用关联接口</el-checkbox></el-form-item>
        <template v-if="form.reference_enabled">
          <el-form-item label="关联接口" prop="reference_interface"><el-select v-model="form.reference_interface" filterable placeholder="请选择需要关联的接口" style="width:100%"><template v-for="item in referenceInterfaces" :key="item.id"><el-option v-if="item.id !== form.id" :label="`${item.name} · ${item.method} ${item.path}`" :value="item.id" /></template></el-select></el-form-item>
          <el-form-item label="提取返回值"><div class="extract-rule-list"><div v-for="(item, index) in form.response_extracts" :key="index" class="extract-rule-row"><el-input v-model="item.name" placeholder="保存变量名，如 token" /><el-input v-model="item.path" placeholder="JSON 路径，如 data.token" /><el-button type="danger" link @click="removeExtract(index)">删除</el-button></div><el-button type="primary" link @click="addExtract">+ 添加返回值</el-button></div></el-form-item>
        </template>
        <el-form-item label="Headers" prop="headersText"><el-input v-model="form.headersText" type="textarea" :rows="4" placeholder='{"Content-Type": "application/json; charset=utf-8"}' /></el-form-item>
        <el-form-item label="请求参数" prop="requestParamsText"><el-input v-model="form.requestParamsText" type="textarea" :rows="5" placeholder='{"body":{"name":"{{personName}}","phone":"{{mobile}}"}}' /><small class="extract-help">参数化值支持 &#123;&#123;变量名&#125;&#125; 或 ${变量名}；关联接口变量优先使用已提取值。</small></el-form-item>
        <el-form-item label="参数化配置"><div class="extract-rule-list"><div v-for="(item, index) in form.parameterizations" :key="index" class="extract-rule-row"><el-input v-model="item.name" placeholder="变量名，如 personName" /><el-select v-model="item.type" placeholder="数据类型" style="width:150px"><el-option label="人名" value="name"/><el-option label="时间" value="time"/><el-option label="地点" value="location"/><el-option label="手机号" value="phone"/><el-option label="身份证" value="id_card"/><el-option label="邮箱" value="email"/><el-option label="自定义" value="custom"/></el-select><el-input v-if="item.type === 'custom'" v-model="item.value" placeholder="自定义值" /><el-button type="danger" link @click="removeParameterization(index)">删除</el-button></div><el-button type="primary" link @click="addParameterization">+ 添加参数化参数</el-button></div></el-form-item>
        <el-form-item label="接口断言" prop="assertionsText"><el-input v-model="form.assertionsText" type="textarea" :rows="5" placeholder='{"status_code": 200, "json_path": "data.id", "expected_value": 1}' /></el-form-item>
        <el-form-item label="接口描述"><el-input v-model="form.description" type="textarea" :rows="3" /></el-form-item>
        <el-checkbox v-model="form.can_execute_in_task">允许被任务执行</el-checkbox>
      </el-form>
      <template #footer><el-button @click="dialog = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="batchDialog" title="批量录入接口" width="760">
      <el-form label-position="top">
        <el-form-item label="业务模块"><el-select v-model="batchModule" clearable placeholder="自动识别业务模块" style="width:100%"><el-option v-for="item in BUSINESS_MODULES" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        <el-form-item label="Fetch 请求文本"><el-input v-model="batchText" type="textarea" :rows="18" placeholder="请粘贴一个或多个 fetch(...) 请求" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="batchDialog = false">取消</el-button><el-button type="primary" :loading="batchSaving" :disabled="!batchText.trim()" @click="batchImport">录入</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import dayjs from 'dayjs'
import * as api from '@/api'
import { BUSINESS_MODULES } from '@/constants'
import { installOverflowTooltip } from '@/overflowTooltip'
import { Upload } from '@element-plus/icons-vue'
import type { ApiInterface, ApiParameterization, ApiResponseExtract } from '@/types'

const defaultHeaders = { 'Content-Type': 'application/json; charset=utf-8', authorization: '' }
const defaultAssertions = { status_code: 200, timeout_seconds: 3, json_path: 'code', expected_value: 0 }
const methods = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']
const pageSizes = [10, 50, 100]
const interfaces = ref<ApiInterface[]>([])
const referenceInterfaces = ref<ApiInterface[]>([])
const total = ref(0)
const loading = ref(false)
const saving = ref(false)
const batchSaving = ref(false)
const batchDialog = ref(false)
const batchText = ref('')
const batchModule = ref('')
const dialog = ref(false)
const formRef = ref<FormInstance>()
const query = reactive({ keyword: '', module_name: [] as string[], page: 1, pageSize: 10 })
const form = reactive({ id: 0, name: '', method: 'GET', path: '', module_name: '', api_type: '系统录入', description: '', headersText: JSON.stringify(defaultHeaders, null, 2), requestParamsText: '', parameterizations: [] as ApiParameterization[], assertionsText: JSON.stringify(defaultAssertions, null, 2), reference_enabled: false, reference_interface: null as number | null, response_extracts: [] as ApiResponseExtract[], can_execute_in_task: true })

function applyModuleTokenHeader() {
  if (form.id) return
  const headers = JSON.parse(form.headersText || '{}')
  for (const key of Object.keys(headers)) if (/^(authorization|x-token|x-access-token)$/i.test(key)) delete headers[key]
  headers[form.module_name === '后台' ? 'x-token' : 'authorization'] = ''
  form.headersText = JSON.stringify(headers, null, 2)
}

function jsonObjectRule(label: string, required = false) {
  return (_rule: unknown, value: string, callback: (error?: Error) => void) => {
    if (required && !value.trim()) return callback(new Error(`请输入${label}`))
    try {
      const parsed = JSON.parse(value || '{}')
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return callback(new Error(`${label}必须是 JSON 对象`))
      if (required && !Object.keys(parsed).length) return callback(new Error(`${label}不能为空`))
      callback()
    } catch { callback(new Error(`${label}格式不正确`)) }
  }
}

const rules: FormRules = {
  name: [{ required: true, message: '请输入接口名称' }], method: [{ required: true, message: '请选择请求方法' }], path: [{ required: true, message: '请输入请求路径' }], module_name: [{ required: true, message: '请选择业务模块' }], api_type: [{ required: true, message: '请选择接口类型' }], headersText: [{ validator: jsonObjectRule('Headers'), trigger: 'blur' }], requestParamsText: [{ validator: jsonObjectRule('请求参数'), trigger: 'blur' }], assertionsText: [{ validator: jsonObjectRule('接口断言'), trigger: 'blur' }]
}

async function load() { loading.value = true; try { const res = await api.getInterfaces({ ...query, module_name: query.module_name.join(',') }); interfaces.value = res.data.list.map(item => ({ ...item, api_type: '系统录入' })); total.value = res.data.total } catch (e) { ElMessage.error((e as Error).message) } finally { loading.value = false } }
async function loadReferenceInterfaces() { try { const res = await api.getInterfaces({ pageSize: 100 }); referenceInterfaces.value = res.data.list.map(item => ({ ...item, api_type: '系统录入' })) } catch (e) { ElMessage.error((e as Error).message) } }
function filterInterfaces() { query.page = 1; void load() }
function changePageSize() { query.page = 1; void load() }
function addExtract() { form.response_extracts.push({ name: '', path: '' }) }
function removeExtract(index: number) { form.response_extracts.splice(index, 1) }
function addParameterization() { form.parameterizations.push({ name: '', type: 'name' }) }
function removeParameterization(index: number) { form.parameterizations.splice(index, 1) }
function openForm(item?: ApiInterface) {
  Object.assign(form, item ? { id: item.id, name: item.name, method: item.method, path: item.path, module_name: item.module_name, api_type: '系统录入', description: item.description, headersText: JSON.stringify(item.headers || {}, null, 2), requestParamsText: Object.keys(item.request_params || {}).length ? JSON.stringify(item.request_params, null, 2) : '', parameterizations: (item.parameterizations || []).map(rule => ({ ...rule })), assertionsText: JSON.stringify(Object.keys(item.assertions || {}).length ? item.assertions : defaultAssertions, null, 2), reference_enabled: item.reference_enabled, reference_interface: item.reference_interface, response_extracts: (item.response_extracts || []).map(rule => ({ ...rule })), can_execute_in_task: item.can_execute_in_task } : { id: 0, name: '', method: 'GET', path: '', module_name: '', api_type: '系统录入', description: '', headersText: JSON.stringify(defaultHeaders, null, 2), requestParamsText: '', parameterizations: [], assertionsText: JSON.stringify(defaultAssertions, null, 2), reference_enabled: false, reference_interface: null, response_extracts: [], can_execute_in_task: true }); dialog.value = true; void loadReferenceInterfaces() }
async function save() {
  if (!await formRef.value?.validate().catch(() => false)) return
  const extractNames = form.response_extracts.map(item => item.name.trim())
  if (form.reference_enabled && (!form.reference_interface || !form.response_extracts.length || form.response_extracts.some(item => !item.name.trim() || !item.path.trim()))) { ElMessage.error('请完整配置关联接口和返回值提取规则'); return }
  if (form.reference_enabled && new Set(extractNames).size !== extractNames.length) { ElMessage.error('响应提取变量名不能重复'); return }
  saving.value = true
  try {
    const payload = { name: form.name, method: form.method, path: form.path, module_name: form.module_name, api_type: '系统录入', description: form.description, headers: JSON.parse(form.headersText || '{}'), request_params: JSON.parse(form.requestParamsText || '{}'), parameterizations: form.parameterizations, assertions: JSON.parse(form.assertionsText || '{}'), reference_enabled: form.reference_enabled, reference_interface: form.reference_enabled ? form.reference_interface : null, response_extracts: form.reference_enabled ? form.response_extracts : [], can_execute_in_task: form.can_execute_in_task }
    form.id ? await api.updateInterface(form.id, payload) : await api.createInterface(payload)
    dialog.value = false; await load(); ElMessage.success('接口保存成功')
  } catch (e) { ElMessage.error((e as Error).message) } finally { saving.value = false }
}
async function batchImport() {
  const text = batchText.value.trim()
  if (!text) return
  batchSaving.value = true
  try {
    const res = await api.batchImportInterfaces({ text, module_name: batchModule.value })
    const result = res.data
    batchDialog.value = false
    batchText.value = ''
    batchModule.value = ''
    await load()
    const failed = result.failed?.length || 0
    const skipped = result.skipped?.length || 0
    ElMessage.success(`批量录入完成：成功 ${result.imported.length} 条，重复跳过 ${skipped} 条${failed ? `，失败 ${failed} 条` : ''}`)
  } catch (e) { ElMessage.error((e as Error).message) } finally { batchSaving.value = false }
}
async function toggleExecutable(item: ApiInterface) { try { await api.updateInterface(item.id, { can_execute_in_task: item.can_execute_in_task }); ElMessage.success(item.can_execute_in_task ? '已允许任务执行' : '已禁止任务执行') } catch (e) { item.can_execute_in_task = !item.can_execute_in_task; ElMessage.error((e as Error).message) } }
async function remove(item: ApiInterface) { try { await ElMessageBox.confirm(`确定删除接口“${item.name}”吗？`, '删除接口', { type: 'warning' }); await api.deleteInterface(item.id); await load(); ElMessage.success('接口已删除') } catch (e) { if (e !== 'cancel') ElMessage.error((e as Error).message) } }
function methodType(value: string) { return value === 'GET' ? 'success' : value === 'POST' ? 'primary' : value === 'DELETE' ? 'danger' : 'warning' }
function formatTime(value: string) { return dayjs(value).format('YYYY-MM-DD HH:mm') }
let removeOverflowTooltip = () => {}
onMounted(() => { removeOverflowTooltip = installOverflowTooltip(); void load() })
onUnmounted(() => removeOverflowTooltip())
</script>

<style scoped>
.muted-text { color: #98a2b3; font-size: 12px; }
.extract-rule-list { width: 100%; display: grid; gap: 8px; }
.extract-rule-row { display: grid; grid-template-columns: 1fr 1.5fr auto; gap: 8px; align-items: center; }
.extract-help { display: block; margin-top: 5px; color: #98a2b3; font-size: 12px; line-height: 1.5; }
</style>
