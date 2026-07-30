<template>
  <section class="surface monitor-page">
    <div class="monitor-toolbar">
      <el-input v-model="query.keyword" clearable placeholder="搜索任务名称或模块" @input="filterData"/>
      <el-select v-model="query.enabled" clearable placeholder="全部状态" @change="filterData"><el-option label="启用" value="true"/><el-option label="停用" value="false"/></el-select>
      <span>共 {{total}} 个监控任务</span>
      <el-button type="primary" @click="openForm()"><el-icon><Plus/></el-icon>新建任务</el-button>
    </div>
    <el-table v-loading="loading" :data="tasks" empty-text="暂无监控任务">
      <el-table-column prop="name" label="任务名称" min-width="180"/>
      <el-table-column prop="module_name" label="业务模块" width="110"/>
      <el-table-column prop="api_type" label="接口类型" width="100"><template #default="{row}">{{row.api_type||'-'}}</template></el-table-column>
      <el-table-column prop="environment_name" label="环境" width="120"/>
      <el-table-column prop="api_count" label="接口数" width="82"/>
      <el-table-column prop="failure_count" label="失败数" width="82"><template #default="{row}"><span :class="{'failure-count':row.failure_count>0}">{{row.failure_count}}</span></template></el-table-column>
      <el-table-column label="周期" width="105"><template #default="{row}">{{row.interval_value}}{{row.interval_unit_name}}</template></el-table-column>
      <el-table-column label="结果" width="95"><template #default="{row}"><el-tag :type="statusType(row.status)">{{row.status_name}}</el-tag></template></el-table-column>
      <el-table-column label="启用" width="86"><template #default="{row}"><el-switch v-model="row.enabled" @change="toggle(row)"/></template></el-table-column>
      <el-table-column label="最近执行" width="155"><template #default="{row}">{{row.last_run_time?formatTime(row.last_run_time):'-'}}</template></el-table-column>
      <el-table-column label="下次执行" width="155"><template #default="{row}">{{row.next_run_time?formatTime(row.next_run_time):'-'}}</template></el-table-column>
      <el-table-column label="操作" width="220" fixed="right"><template #default="{row}"><el-button link type="primary" @click="openForm(row)">编辑</el-button><el-button link type="primary" :loading="runningId===row.id" @click="runNow(row)">立即执行</el-button><el-button link type="primary" @click="showHistory(row)">详情</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="query.page" :total="total" :page-size="10" layout="total, prev, pager, next" @current-change="load"/>
  </section>

  <el-dialog v-model="dialog" :title="form.id?'编辑监控任务':'新建监控任务'" width="640">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="任务名称" prop="name"><el-input v-model="form.name"/></el-form-item>
      <el-row :gutter="16"><el-col :span="12"><el-form-item label="接口类型" prop="api_type"><el-select v-model="form.api_type" filterable style="width:100%"><el-option v-for="item in availableTypes" :key="item" :label="item" :value="item"/></el-select></el-form-item></el-col><el-col :span="12"><el-form-item label="运行环境" prop="environment"><el-select v-model="form.environment" style="width:100%"><el-option v-for="env in environments" :key="env.id" :label="env.name" :value="env.id"/></el-select></el-form-item></el-col></el-row>
      <el-form-item label="执行周期" prop="interval_value"><el-input-number v-model="form.interval_value" :min="1" :max="1440" controls-position="right"/><el-select v-model="form.interval_unit" style="width:100px;margin-left:12px"><el-option label="分钟" value="minute"/><el-option label="小时" value="hour"/><el-option label="天" value="day"/></el-select><span class="frequency-text">执行一次</span></el-form-item>
      <el-checkbox v-model="form.enabled">启用任务</el-checkbox>
    </el-form>
    <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
  </el-dialog>

  <el-drawer v-model="detailVisible" title="监控执行详情" size="min(980px, 94vw)">
    <template v-if="currentTask">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="任务名称">{{currentTask.name}}</el-descriptions-item>
        <el-descriptions-item label="执行结果"><el-tag :type="statusType(currentExecution?.status||currentTask.status)">{{currentExecution?.status_name||currentTask.status_name}}</el-tag></el-descriptions-item>
        <el-descriptions-item label="环境">{{currentTask.environment_name}}</el-descriptions-item>
        <el-descriptions-item label="失败数量"><span :class="{'failure-count':(currentExecution?.failure_count||0)>0}">{{currentExecution?.failure_count||0}}</span></el-descriptions-item>
        <el-descriptions-item label="平均耗时"><span :class="{'danger-text':(currentExecution?.average_duration_ms||0)>3000}">{{currentExecution?.average_duration_ms||0}} ms</span></el-descriptions-item>
        <el-descriptions-item label="执行信息"><span :class="{'danger-text':currentExecution?.status==='failed'}">{{currentExecution?.message||'-'}}</span></el-descriptions-item>
      </el-descriptions>
      <div class="execution-detail-head"><strong>执行批次</strong><span>共 {{history.length}} 次</span></div>
      <el-table :data="history" max-height="210" @row-click="selectExecution">
        <el-table-column prop="execution_no" label="批次" width="70"/>
        <el-table-column label="结果" width="92"><template #default="{row}"><el-tag :type="statusType(row.status)" size="small">{{row.status_name}}</el-tag></template></el-table-column>
        <el-table-column prop="interface_total" label="接口数" width="80"/>
        <el-table-column prop="failure_count" label="失败数" width="80"><template #default="{row}"><span :class="{'failure-count':row.failure_count>0}">{{row.failure_count}}</span></template></el-table-column>
        <el-table-column label="平均耗时" width="100"><template #default="{row}"><span :class="{'danger-text':row.average_duration_ms>3000}">{{row.average_duration_ms}} ms</span></template></el-table-column>
        <el-table-column prop="message" label="执行信息" min-width="220"/>
        <el-table-column label="开始时间" width="155"><template #default="{row}">{{formatTime(row.started_at)}}</template></el-table-column>
      </el-table>
      <div class="execution-detail-head"><strong>接口明细</strong><span>共 {{currentExecution?.details.length||0}} 个接口</span></div>
      <el-table :data="currentExecution?.details||[]" empty-text="暂无接口明细" max-height="420">
        <el-table-column prop="interface_name" label="接口名称" min-width="150"/>
        <el-table-column label="方法" width="82"><template #default="{row}"><el-tag effect="plain" size="small">{{row.method}}</el-tag></template></el-table-column>
        <el-table-column prop="url" label="完整 URL" min-width="230"><template #default="{row}"><code>{{row.url}}</code></template></el-table-column>
        <el-table-column label="结果" width="88"><template #default="{row}"><el-tag :type="statusType(row.status)" size="small">{{row.status_name}}</el-tag></template></el-table-column>
        <el-table-column label="耗时" width="88"><template #default="{row}"><span :class="{'danger-text':(row.duration_ms||0)>3000}">{{formatDuration(row.duration_ms)}}</span></template></el-table-column>
        <el-table-column prop="response_message" label="执行信息" min-width="180"><template #default="{row}"><span :class="{'danger-text':row.status==='failed'}">{{row.response_message}}</span></template></el-table-column>
        <el-table-column label="操作" width="82" fixed="right"><template #default="{row}"><el-button link type="primary" :loading="retryingId===row.id" @click="retryDetail(row.id)">重试</el-button></template></el-table-column>
      </el-table>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed,onMounted,onUnmounted,reactive,ref } from 'vue';import { ElMessage,ElMessageBox,type FormInstance,type FormRules } from 'element-plus';import dayjs from 'dayjs';import * as api from '@/api';import { installOverflowTooltip } from '@/overflowTooltip';import type { Environment,MonitorExecution,MonitorTask } from '@/types'
const tasks=ref<MonitorTask[]>([]),environments=ref<Environment[]>([]),history=ref<MonitorExecution[]>([]),apiTypeOptions=ref<string[]>([])
const total=ref(0),loading=ref(false),saving=ref(false),runningId=ref(0),retryingId=ref(0),dialog=ref(false),detailVisible=ref(false),currentTask=ref<MonitorTask|null>(null),currentExecution=ref<MonitorExecution|null>(null),formRef=ref<FormInstance>(),query=reactive({keyword:'',enabled:'',page:1})
const form=reactive({id:0,name:'',api_type:'',environment:0,interval_value:1,interval_unit:'minute' as 'minute'|'hour'|'day',enabled:true})
const availableTypes=computed(()=>Array.from(new Set([...apiTypeOptions.value,...tasks.value.map(item=>item.api_type).filter(Boolean)])).sort())
const rules:FormRules={name:[{required:true,message:'请输入任务名称'}],api_type:[{required:true,message:'请选择接口类型'}],environment:[{required:true,message:'请选择运行环境'}],interval_value:[{required:true,message:'请输入执行间隔'}]}
async function load(){loading.value=true;try{const res=await api.getMonitorTasks({...query,pageSize:10});tasks.value=res.data.list;total.value=res.data.total}catch(e){ElMessage.error((e as Error).message)}finally{loading.value=false}}
async function loadOptions(){const [envRes,monitorRes,automationRes]=await Promise.all([api.getEnvironments(),api.getMonitorInterfaces({pageSize:100}),api.getInterfaces({pageSize:100,can_execute_in_task:true})]);environments.value=Array.isArray(envRes)?envRes:envRes.data;apiTypeOptions.value=Array.from(new Set([...monitorRes.data.list.map(item=>item.api_type),...automationRes.data.list.map(item=>item.api_type)].filter(Boolean))).sort()}
function filterData(){query.page=1;void load()}
function openForm(item?:MonitorTask){Object.assign(form,item?{id:item.id,name:item.name,api_type:item.api_type||'',environment:item.environment,interval_value:item.interval_value,interval_unit:item.interval_unit,enabled:item.enabled}:{id:0,name:'',api_type:'',environment:(environments.value.find(item=>item.is_default)||environments.value[0])?.id||0,interval_value:1,interval_unit:'minute',enabled:true});dialog.value=true;void loadOptions()}
async function save(){if(!await formRef.value?.validate().catch(()=>false))return;saving.value=true;try{const payload={name:form.name.trim(),api_type:form.api_type,environment:form.environment,interval_value:form.interval_value,interval_unit:form.interval_unit,enabled:form.enabled,notification:{enabled:false}};form.id?await api.updateMonitorTask(form.id,payload):await api.createMonitorTask(payload);dialog.value=false;await load();ElMessage.success('监控任务保存成功')}catch(e){ElMessage.error((e as Error).message)}finally{saving.value=false}}
async function toggle(item:MonitorTask){try{await api.toggleMonitorTask(item.id,item.enabled);await load();ElMessage.success(item.enabled?'任务已启用':'任务已停用')}catch(e){item.enabled=!item.enabled;ElMessage.error((e as Error).message)}}
async function runNow(item:MonitorTask){runningId.value=item.id;try{await api.runMonitorTask(item.id);await load();ElMessage.success('监控任务执行完成')}catch(e){ElMessage.error((e as Error).message)}finally{runningId.value=0}}
async function showHistory(item:MonitorTask){currentTask.value=item;detailVisible.value=true;await loadHistory(item.id)}
async function loadHistory(taskId:number){const res=await api.getMonitorTaskHistory(taskId,{pageSize:20});history.value=res.data.list;currentExecution.value=history.value[0]||null}
function selectExecution(row:MonitorExecution){currentExecution.value=row}
async function retryDetail(id:number){if(!currentTask.value)return;retryingId.value=id;try{await api.retryMonitorExecutionDetail(id);await loadHistory(currentTask.value.id);await load();ElMessage.success('监控接口重试完成')}catch(e){ElMessage.error((e as Error).message)}finally{retryingId.value=0}}
async function remove(item:MonitorTask){try{await ElMessageBox.confirm(`确定删除监控任务“${item.name}”吗？执行历史和报警也会一并删除。`,'删除监控任务',{type:'warning'});await api.deleteMonitorTask(item.id);await load();ElMessage.success('监控任务已删除')}catch(e){if(e!=='cancel')ElMessage.error((e as Error).message)}}
function statusType(value:string){return value==='passed'?'success':value==='failed'?'danger':value==='running'?'primary':'info'}function formatDuration(value:number|null){return value===null?'-':`${value} ms`}function formatTime(value:string){return dayjs(value).format('YYYY-MM-DD HH:mm:ss')}
let removeOverflowTooltip=()=>{}
onMounted(async()=>{removeOverflowTooltip=installOverflowTooltip();try{await loadOptions();await load()}catch(e){ElMessage.error((e as Error).message)}})
onUnmounted(()=>removeOverflowTooltip())
</script>
