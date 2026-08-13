<template>
  <section class="surface monitor-page scene-package-page">
    <div class="monitor-toolbar">
      <el-input v-model="keyword" clearable placeholder="搜索场景名称或描述" @keyup.enter="search" @clear="search"><template #prefix><el-icon><Search /></el-icon></template></el-input>
      <el-button @click="search">查询</el-button>
      <span>共 {{ total }} 个场景</span>
      <el-button v-if="hasPermission('automation.scene_package.manage')" class="toolbar-action" type="primary" @click="openForm()"><el-icon><Plus /></el-icon>新建场景</el-button>
    </div>
    <el-table v-loading="loading" :data="packages" empty-text="暂无场景包">
      <el-table-column prop="name" label="场景名称" min-width="220" show-overflow-tooltip />
      <el-table-column prop="interface_count" label="接口数量" width="110" align="center" />
      <el-table-column prop="description" label="描述" min-width="260" show-overflow-tooltip />
      <el-table-column prop="created_by_name" label="创建人" width="120" show-overflow-tooltip />
      <el-table-column label="创建时间" width="180"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" width="230" fixed="right"><template #default="{ row }"><el-button v-if="hasPermission('automation.scene_package.manage')" link type="primary" @click="openExecute(row)">执行</el-button><el-button link type="primary" @click="openDetail(row)">详情</el-button><el-button v-if="hasPermission('automation.scene_package.manage')" link type="primary" @click="openForm(row)">编辑</el-button><el-button v-if="hasPermission('automation.scene_package.manage')" link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[10, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="changePageSize" />

    <el-dialog v-model="dialog" :title="form.id ? '编辑场景' : '新建场景'" width="min(980px, 94vw)" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="场景名称" prop="name"><el-input v-model="form.name" maxlength="100" show-word-limit /></el-form-item>
        <el-form-item label="选择接口" prop="interface_ids">
          <el-select v-model="form.interface_ids" multiple filterable collapse-tags collapse-tags-tooltip :loading="interfacesLoading" placeholder="请选择场景接口，选择后可拖动调整执行顺序" style="width:100%" @change="syncSelectedOrder">
            <el-option v-for="item in interfaces" :key="item.id" :label="`${item.name} · ${item.method} ${item.path}`" :value="item.id" />
          </el-select>
        </el-form-item>
        <div class="selected-head"><strong>已选择接口</strong><span>拖动列表调整后续执行顺序</span></div>
        <el-table v-if="selectedInterfaces.length" :data="selectedInterfaces" row-key="id" class="selected-table" empty-text="暂无接口">
          <el-table-column label="顺序" width="70" align="center"><template #default="{ $index }"><span class="drag-handle" draggable="true" title="拖动排序" @dragstart="dragStart($index, $event)" @dragover.prevent @drop="drop($index)"><el-icon><Rank /></el-icon>{{ $index + 1 }}</span></template></el-table-column>
          <el-table-column prop="module_name" label="模块" width="130" show-overflow-tooltip />
          <el-table-column prop="name" label="接口名称" min-width="180" show-overflow-tooltip />
          <el-table-column label="接口 URL" min-width="260" show-overflow-tooltip><template #default="{ row }"><code>{{ row.method }} {{ row.path }}</code></template></el-table-column>
          <el-table-column label="参数" min-width="220"><template #default="{ row }"><el-tooltip :content="formatJson(row.request_params)" placement="top"><span class="param-preview">{{ formatJson(row.request_params) }}</span></el-tooltip></template></el-table-column>
        </el-table>
        <el-empty v-else description="请选择接口后查看执行明细" :image-size="70" />
        <el-form-item label="描述"><el-input v-model="form.description" type="textarea" :rows="4" maxlength="500" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
    </el-dialog>

    <el-dialog v-model="executeDialog" title="执行场景" width="500" destroy-on-close>
      <el-form :model="executeForm" label-position="top">
        <el-form-item label="环境包" required><el-select v-model="executeForm.environment_package" placeholder="请选择环境包" style="width:100%"><el-option v-for="pkg in environmentPackages" :key="pkg.id" :label="pkg.name" :value="pkg.id" /></el-select></el-form-item>
        <el-form-item label="目标系统登录密码" required><el-input v-model="executeForm.login_password" type="password" show-password autocomplete="new-password" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="executeDialog=false">取消</el-button><el-button type="primary" :loading="executeSaving" @click="execute">开始执行</el-button></template>
    </el-dialog>

    <el-drawer v-model="detailVisible" title="场景执行详情" size="min(1180px, 96vw)">
      <template v-if="detailPackage">
        <div class="execution-detail-head"><strong>执行记录</strong><span>共 {{ detailTotal }} 次，点击记录查看接口明细</span></div>
        <el-table v-loading="detailLoading" :data="detailTasks" empty-text="暂无执行记录" row-key="id" highlight-current-row @row-click="selectDetailTask">
          <el-table-column type="index" label="序号" width="62" />
          <el-table-column label="执行状态" width="100"><template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status_name }}</el-tag></template></el-table-column>
          <el-table-column prop="environment_name" label="环境" min-width="140" show-overflow-tooltip />
          <el-table-column prop="interface_count" label="接口数量" width="90" />
          <el-table-column prop="failure_count" label="失败数量" width="90"><template #default="{ row }"><span :class="{ 'failure-count': row.failure_count > 0 }">{{ row.failure_count }}</span></template></el-table-column>
          <el-table-column prop="owner_name" label="执行人" width="100" />
          <el-table-column label="执行时间" width="165"><template #default="{ row }">{{ formatTime(row.created_at) }}</template></el-table-column>
        </el-table>
        <el-pagination v-model:current-page="detailPage" v-model:page-size="detailPageSize" :page-sizes="[10, 50, 100]" :total="detailTotal" layout="total, sizes, prev, pager, next" @current-change="loadHistory" @size-change="changeDetailPageSize" />
        <template v-if="detailTask">
        <div class="execution-summary">
          <div><span>执行状态</span><b><el-tag :type="statusType(detailTask.status)">{{ detailTask.status_name }}</el-tag></b></div>
          <div><span>环境</span><b>{{ detailTask.environment_name || '-' }}</b></div>
          <div><span>接口总数</span><b>{{ detailTask.interface_count }}</b></div>
          <div><span>失败数量</span><b :class="{ 'danger-text': detailTask.failure_count > 0 }">{{ detailTask.failure_count }}</b></div>
        </div>
        <div class="execution-detail-head"><strong>接口执行明细</strong><span>共 {{ detailTask.execution_details.length }} 条</span></div>
        <el-table class="execution-detail-table" :data="detailTask.execution_details" empty-text="暂无接口执行明细" max-height="620">
          <el-table-column type="index" label="序号" width="62" />
          <el-table-column prop="interface_name" label="接口名称" min-width="150" />
          <el-table-column label="方法" width="82"><template #default="{ row }"><el-tag effect="plain" size="small">{{ row.method }}</el-tag></template></el-table-column>
          <el-table-column prop="path" label="请求路径" min-width="220" show-overflow-tooltip />
          <el-table-column label="请求参数" min-width="260"><template #default="{ row }"><el-tooltip :content="formatJson(row.request_params)" placement="top"><pre class="scenario-json execution-detail-clamp execution-detail-json">{{ formatJson(row.request_params) }}</pre></el-tooltip></template></el-table-column>
          <el-table-column label="结果" width="90"><template #default="{ row }"><el-tag :type="statusType(row.status)" size="small">{{ row.status_name }}</el-tag></template></el-table-column>
          <el-table-column label="耗时" width="90"><template #default="{ row }">{{ formatDuration(row.duration_ms) }}</template></el-table-column>
          <el-table-column label="执行时间" width="160"><template #default="{ row }">{{ row.executed_at ? formatTime(row.executed_at) : '-' }}</template></el-table-column>
          <el-table-column prop="response_message" label="执行信息" min-width="180" show-overflow-tooltip />
          <el-table-column label="操作" width="90" fixed="right"><template #default="{ row }"><el-button link type="warning" :disabled="row.status !== 'failed'" @click="showLog(row)">日志</el-button></template></el-table-column>
        </el-table>
        </template>
      </template>
    </el-drawer>

    <el-dialog v-model="logVisible" :title="`执行日志 - ${currentLogName}`" width="720">
      <section class="execution-log-section"><h3>实际请求</h3><pre class="execution-log">{{ currentRequestParams }}</pre></section>
      <section class="execution-log-section"><h3>接口返回信息</h3><pre class="execution-log">{{ currentLog }}</pre></section>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from 'element-plus'
import { hasPermission } from '@/auth'
import * as api from '@/api'
import type { ApiInterface, AutomationTask, EnvironmentPackage, MonitorScenePackage } from '@/types'

const loading = ref(false), interfacesLoading = ref(false), saving = ref(false), dialog = ref(false), executeDialog = ref(false), executeSaving = ref(false), detailVisible = ref(false), detailLoading = ref(false), logVisible = ref(false)
const formRef = ref<FormInstance>(), keyword = ref(''), packages = ref<MonitorScenePackage[]>([]), interfaces = ref<ApiInterface[]>([])
const environmentPackages = ref<EnvironmentPackage[]>([]), executePackage = ref<MonitorScenePackage | null>(null), detailTask = ref<AutomationTask | null>(null), detailPackage = ref<MonitorScenePackage | null>(null), detailTasks = ref<AutomationTask[]>([])
const currentLog = ref(''), currentRequestParams = ref(''), currentLogName = ref('')
let detailPollTimer: ReturnType<typeof setTimeout> | undefined
const total = ref(0), page = ref(1), pageSize = ref(10), detailTotal = ref(0), detailPage = ref(1), detailPageSize = ref(10), draggingIndex = ref(-1), orderedIds = ref<number[]>([])
const form = reactive({ id: 0, name: '', description: '', interface_ids: [] as number[] })
const executeForm = reactive({ environment_package: 0, login_password: '' })
const rules: FormRules = { name: [{ required: true, message: '请输入场景名称', trigger: 'blur' }], interface_ids: [{ type: 'array', required: true, message: '请选择至少一个接口', trigger: 'change' }] }
const selectedInterfaces = computed(() => form.interface_ids.map(id => interfaces.value.find(item => item.id === id)).filter((item): item is ApiInterface => Boolean(item)))
function formatTime(value: string) { return value ? dayjs(value).format('YYYY-MM-DD HH:mm:ss') : '-' }
function formatJson(value: Record<string, unknown>) { const text = JSON.stringify(value || {}); return text.length > 100 ? `${text.slice(0, 100)}...` : text }
function formatDuration(value: number | null) { return value == null ? '-' : `${value} ms` }
function statusType(status: string) { return status === 'passed' ? 'success' : status === 'failed' ? 'danger' : status === 'running' ? 'warning' : 'info' }
function showLog(detail: AutomationTask['execution_details'][number]) { const headers = Object.fromEntries(Object.entries(detail.headers || {}).map(([key, value]) => /authorization|x-token/i.test(key) ? [key, '***'] : [key, value])); currentLogName.value = detail.interface_name; currentRequestParams.value = JSON.stringify({ method: detail.method, url: detail.path, headers, params: detail.request_params || {} }, null, 2); currentLog.value = detail.response_log || detail.response_message || '接口未返回具体信息'; logVisible.value = true }
async function load() { loading.value = true; try { const res = await api.getMonitorScenePackages({ keyword: keyword.value.trim() || undefined, page: page.value, pageSize: pageSize.value }); packages.value = res.data.list; total.value = res.data.total } catch (error) { ElMessage.error((error as Error).message) } finally { loading.value = false } }
function search() { page.value = 1; void load() }
function changePageSize() { page.value = 1; void load() }
async function loadInterfaces() { interfacesLoading.value = true; try { const response = await api.getInterfaces({ page: 1, pageSize: 100 }); interfaces.value = response.data.list || [] } catch (error) { ElMessage.error((error as Error).message) } finally { interfacesLoading.value = false } }
async function loadEnvironmentPackages() { try { const response = await api.getEnvironmentPackages(); environmentPackages.value = Array.isArray(response) ? response : response.data || [] } catch (error) { ElMessage.error((error as Error).message) } }
function resetForm(item?: MonitorScenePackage) { const ids = item ? item.items.map(row => row.interface_id) : []; orderedIds.value = [...ids]; Object.assign(form, item ? { id: item.id, name: item.name, description: item.description, interface_ids: ids } : { id: 0, name: '', description: '', interface_ids: [] }) }
function openForm(item?: MonitorScenePackage) { if (!hasPermission('automation.scene_package.manage')) return; resetForm(item); dialog.value = true; void loadInterfaces() }
function syncSelectedOrder(ids: number[]) { const next = orderedIds.value.filter(id => ids.includes(id)).concat(ids.filter(id => !orderedIds.value.includes(id))); orderedIds.value = next; form.interface_ids = next }
function dragStart(index: number, event: DragEvent) { draggingIndex.value = index; if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move' }
function drop(index: number) { const source = draggingIndex.value; if (source < 0 || source === index) return; const ids = [...form.interface_ids]; const [moved] = ids.splice(source, 1); ids.splice(index, 0, moved); orderedIds.value = ids; form.interface_ids = ids; draggingIndex.value = -1 }
async function save() { if (!hasPermission('automation.scene_package.manage') || !await formRef.value?.validate().catch(() => false)) return; saving.value = true; try { const payload = { name: form.name.trim(), description: form.description.trim(), interface_ids: [...form.interface_ids] }; form.id ? await api.updateMonitorScenePackage(form.id, payload) : await api.createMonitorScenePackage(payload); dialog.value = false; await load(); ElMessage.success(form.id ? '场景已更新' : '场景已创建') } catch (error) { ElMessage.error((error as Error).message) } finally { saving.value = false } }
async function remove(item: MonitorScenePackage) { if (!hasPermission('automation.scene_package.manage')) return; try { await ElMessageBox.confirm(`确定删除场景“${item.name}”吗？`, '删除场景', { type: 'warning' }); await api.deleteMonitorScenePackage(item.id); if (packages.value.length === 1 && page.value > 1) page.value -= 1; await load(); ElMessage.success('场景已删除') } catch (error) { if (error !== 'cancel') ElMessage.error((error as Error).message) } }
async function openExecute(item: MonitorScenePackage) { if (!hasPermission('automation.scene_package.manage')) return; executePackage.value = item; executeForm.environment_package = environmentPackages.value[0]?.id || 0; executeForm.login_password = ''; if (!environmentPackages.value.length) await loadEnvironmentPackages(); executeForm.environment_package = executeForm.environment_package || environmentPackages.value[0]?.id || 0; executeDialog.value = true }
async function execute() { if (!executePackage.value || !executeForm.environment_package || !executeForm.login_password.trim()) { ElMessage.error('请选择环境包并输入目标系统登录密码'); return } executeSaving.value = true; try { await api.executeMonitorScenePackage(executePackage.value.id, { environment_package: executeForm.environment_package, login_password: executeForm.login_password.trim() }); executeDialog.value = false; await openDetail(executePackage.value); ElMessage.success('场景已创建，正在执行') } catch (error) { ElMessage.error((error as Error).message) } finally { executeSaving.value = false } }
async function openDetail(item: MonitorScenePackage) { detailVisible.value = true; detailPackage.value = item; detailPage.value = 1; detailTask.value = null; await loadHistory() }
async function loadHistory() { if (!detailPackage.value) return; detailLoading.value = true; if (detailPollTimer) clearTimeout(detailPollTimer); try { const response = await api.getMonitorScenePackageHistory(detailPackage.value.id, { page: detailPage.value, pageSize: detailPageSize.value }); detailTasks.value = response.data.list || []; detailTotal.value = response.data.total || 0; const refreshedTask = detailTask.value && detailTasks.value.find(item => item.id === detailTask.value?.id); detailTask.value = refreshedTask || detailTasks.value[0] || null; if (detailTasks.value.some(item => ['pending', 'running'].includes(item.status))) detailPollTimer = setTimeout(() => { if (detailVisible.value) void loadHistory() }, 2000) } catch (error) { ElMessage.error((error as Error).message) } finally { detailLoading.value = false } }
function selectDetailTask(task: AutomationTask) { detailTask.value = task }
function changeDetailPageSize() { detailPage.value = 1; void loadHistory() }
onMounted(() => { void Promise.all([load(), loadInterfaces(), loadEnvironmentPackages()]) })
onUnmounted(() => { if (detailPollTimer) clearTimeout(detailPollTimer) })
</script>

<style scoped>
.scene-package-page { min-height: 100%; }
.toolbar-action { margin-left: 0; }
.selected-head { display: flex; align-items: center; justify-content: space-between; margin: 8px 0 10px; }
.selected-head strong { font-size: 14px; }
.selected-head span { color: #98a2b3; font-size: 12px; }
.selected-table { margin-bottom: 20px; }
.drag-handle { display: inline-flex; align-items: center; gap: 5px; cursor: grab; color: #1768e8; user-select: none; }
.drag-handle:active { cursor: grabbing; }
.selected-table code { display: block; overflow: hidden; color: #475467; background: #f5f7f9; padding: 3px 6px; text-overflow: ellipsis; white-space: nowrap; font: 11px "SFMono-Regular", Consolas, monospace; }
.param-preview { display: block; overflow: hidden; color: #667085; text-overflow: ellipsis; white-space: nowrap; font: 11px "SFMono-Regular", Consolas, monospace; }
</style>
