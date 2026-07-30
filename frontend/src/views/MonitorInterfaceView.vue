<template>
  <section class="surface monitor-page">
    <div class="monitor-toolbar">
      <el-input v-model="query.keyword" clearable placeholder="搜索接口名称或 URL" @input="filterData"/>
      <el-select v-model="query.api_type" clearable placeholder="全部类型" @change="filterData"><el-option v-for="item in apiTypeOptions" :key="item" :label="item" :value="item"/></el-select>
      <span>共 {{total}} 个监控接口</span>
      <el-button type="primary" @click="openForm()"><el-icon><Plus/></el-icon>新建接口</el-button>
    </div>
    <el-table v-loading="loading" :data="items" empty-text="暂无监控接口">
      <el-table-column prop="name" label="任务接口名称" min-width="190"/>
      <el-table-column prop="api_type" label="接口类型" min-width="130"/>
      <el-table-column label="状态" width="90"><template #default="{row}"><el-switch v-model="row.enabled" @change="toggle(row)"/></template></el-table-column>
      <el-table-column prop="created_by_name" label="创建人" width="120"/>
      <el-table-column label="创建时间" width="165"><template #default="{row}">{{formatTime(row.created_at)}}</template></el-table-column>
      <el-table-column label="操作" width="150" fixed="right"><template #default="{row}"><el-button link type="primary" @click="openForm(row)">编辑</el-button><el-button link type="danger" @click="remove(row)">删除</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="query.page" :total="total" :page-size="10" layout="total, prev, pager, next" @current-change="load"/>
  </section>

  <el-dialog v-model="dialog" :title="form.id?'编辑监控接口':'新建监控接口'" width="680">
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
      <el-form-item label="接口类型" prop="api_type">
        <el-select v-model="form.api_type" filterable default-first-option style="width:100%" @change="onApiTypeChange">
          <el-option v-for="item in apiTypeOptions" :key="item" :label="item" :value="item"/>
        </el-select>
      </el-form-item>
      <template v-if="isSystemInput">
        <el-form-item label="从接口列表选择"><el-select v-model="form.source_interfaces" multiple clearable filterable remote reserve-keyword :remote-method="searchSourceInterfaces" :loading="sourceLoading" collapse-tags collapse-tags-tooltip placeholder="可多选接口，选择后会在下方展示对应信息" style="width:100%" @change="applySource"><el-option v-for="item in sourceInterfaces" :key="item.id" :label="`${item.name} · ${item.method} ${item.path}`" :value="item.id"/></el-select></el-form-item>
      </template>
      <el-form-item v-if="isSystemInput" label="任务接口名称"><el-input v-model="form.name" placeholder="选择接口后自动带出，也可手动修改"/></el-form-item>
      <el-table v-if="isSystemInput && selectedSourceInterfaces.length" :data="selectedSourceInterfaces" size="small" border class="monitor-source-preview">
        <el-table-column prop="name" label="接口名称" min-width="150"/>
        <el-table-column prop="method" label="方法" width="90"/>
        <el-table-column prop="path" label="请求路径" min-width="220"><template #default="{row}"><code>{{row.path}}</code></template></el-table-column>
        <el-table-column prop="module_name" label="业务模块" width="110"/>
        <el-table-column prop="api_type" label="类型" width="110"/>
      </el-table>
      <template v-if="!isSystemInput">
        <el-form-item label="任务接口名称" prop="name"><el-input v-model="form.name"/></el-form-item>
        <el-row :gutter="16"><el-col :span="8"><el-form-item label="请求方法" prop="method"><el-select v-model="form.method"><el-option v-for="item in methods" :key="item" :label="item" :value="item"/></el-select></el-form-item></el-col><el-col :span="16"><el-form-item label="请求路径" prop="path"><el-input v-model="form.path" placeholder="/api/example/"/></el-form-item></el-col></el-row>
        <el-form-item label="Headers" prop="headersText"><el-input v-model="form.headersText" type="textarea" :rows="4"/></el-form-item>
        <el-form-item label="请求参数" prop="requestParamsText"><el-input v-model="form.requestParamsText" type="textarea" :rows="5" placeholder='{}'/></el-form-item>
        <el-form-item label="接口断言" prop="assertionsText"><el-input v-model="form.assertionsText" type="textarea" :rows="5"/></el-form-item>
      </template>
      <el-form-item label="接口描述"><el-input v-model="form.description" type="textarea" :rows="3"/></el-form-item>
      <el-checkbox v-model="form.enabled">启用监控</el-checkbox>
    </el-form>
    <template #footer><el-button @click="dialog=false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed,onMounted,onUnmounted,reactive,ref } from 'vue';import { ElMessage,ElMessageBox,type FormInstance,type FormRules } from 'element-plus';import dayjs from 'dayjs';import * as api from '@/api';import { installOverflowTooltip } from '@/overflowTooltip';import type { ApiInterface,MonitorApiConfig } from '@/types'
const methods=['GET','POST','PUT','PATCH','DELETE'],defaultHeaders={'Content-Type':'application/json; charset=utf-8'},defaultAssertions={status_code:200,timeout_seconds:3}
const items=ref<MonitorApiConfig[]>([]),sourceInterfaces=ref<ApiInterface[]>([]),total=ref(0),loading=ref(false),sourceLoading=ref(false),saving=ref(false),dialog=ref(false),formRef=ref<FormInstance>(),query=reactive({keyword:'',api_type:'',page:1})
const form=reactive({id:0,source_interface:null as number|null,source_interface_ids:[] as number[],source_interfaces:[] as number[],name:'',method:'GET',path:'',module_name:'',api_type:'系统录入',description:'',headersText:JSON.stringify(defaultHeaders,null,2),requestParamsText:'{}',assertionsText:JSON.stringify(defaultAssertions,null,2),enabled:true})
const apiTypeOptions=ref<string[]>([])
const isSystemInput=computed(()=>form.api_type==='系统录入')
const selectedSourceInterfaces=computed(()=>sourceInterfaces.value.filter(row=>form.source_interfaces.includes(row.id)))
function jsonRule(label:string,required:()=>boolean,allowEmptyObject=false){return (_rule:unknown,value:string,callback:(error?:Error)=>void)=>{if(required()&&!value.trim())return callback(new Error(`请输入${label}`));try{const parsed=JSON.parse(value||'{}');if(!parsed||Array.isArray(parsed)||typeof parsed!=='object')return callback(new Error(`${label}必须是 JSON 对象`));if(required()&&!allowEmptyObject&& !Object.keys(parsed).length)return callback(new Error(`${label}不能为空`));callback()}catch{return callback(new Error(`${label}格式不正确`))}}}
const rules:FormRules={name:[{validator:(_rule,value,callback)=>{if(!`${value||''}`.trim())return callback(new Error('请输入任务接口名称'));callback()},trigger:'blur'}],method:[{validator:(_rule,value,callback)=>{if(isSystemInput.value)return callback();if(!`${value||''}`.trim())return callback(new Error('请选择请求方法'));callback()},trigger:'change'}],path:[{validator:(_rule,value,callback)=>{if(isSystemInput.value)return callback();if(!`${value||''}`.trim())return callback(new Error('请输入请求路径'));callback()},trigger:'blur'}],api_type:[{required:true,message:'请选择或输入接口类型',trigger:'change'}],headersText:[{validator:jsonRule('Headers',()=>!isSystemInput.value),trigger:'blur'}],requestParamsText:[{validator:jsonRule('请求参数',()=>!isSystemInput.value,true),trigger:'blur'}],assertionsText:[{validator:jsonRule('接口断言',()=>!isSystemInput.value),trigger:'blur'}]}
async function load(){loading.value=true;try{const res=await api.getMonitorInterfaces({...query,pageSize:10});items.value=res.data.list;total.value=res.data.total;apiTypeOptions.value=[...new Set(items.value.map(item=>item.api_type).filter((item):item is string=>Boolean(item)))]}catch(e){ElMessage.error((e as Error).message)}finally{loading.value=false}}
async function loadSourceInterfaces(keyword=''){sourceLoading.value=true;try{const res=await api.getInterfaces({pageSize:100,keyword});sourceInterfaces.value=res.data.list}finally{sourceLoading.value=false}}
function searchSourceInterfaces(keyword:string){void loadSourceInterfaces(keyword)}
function filterData(){query.page=1;void load()}
function applySource(ids:number[]){const selected=sourceInterfaces.value.filter(row=>ids.includes(row.id));form.source_interface=selected[0]?.id||null;form.source_interface_ids=selected.map(item=>item.id);if(!selected.length)return;const item=selected[0];form.module_name=item.module_name;Object.assign(form,{name:item.name,method:item.method,path:item.path,description:item.description,headersText:JSON.stringify(item.headers||defaultHeaders,null,2),requestParamsText:JSON.stringify(item.request_params||{},null,2),assertionsText:JSON.stringify(Object.keys(item.assertions||{}).length?item.assertions:defaultAssertions,null,2)})}
function onApiTypeChange(){if(form.api_type!=='系统录入'){form.source_interface=null;form.source_interfaces=[]}}
function openForm(item?:MonitorApiConfig){Object.assign(form,item?{id:item.id,source_interface:item.source_interface,source_interface_ids:item.source_interface_ids||[],source_interfaces:item.source_interface_ids?.length?item.source_interface_ids:[item.source_interface].filter((id):id is number=>Boolean(id)),name:item.name,method:item.method,path:item.path,module_name:item.module_name,api_type:item.api_type||'系统录入',description:item.description,headersText:JSON.stringify(item.headers||{},null,2),requestParamsText:JSON.stringify(item.request_params||{},null,2),assertionsText:JSON.stringify(Object.keys(item.assertions||{}).length?item.assertions:defaultAssertions,null,2),enabled:item.enabled}:{id:0,source_interface:null,source_interface_ids:[],source_interfaces:[],name:'',method:'GET',path:'',module_name:'',api_type:'系统录入',description:'',headersText:JSON.stringify(defaultHeaders,null,2),requestParamsText:'{}',assertionsText:JSON.stringify(defaultAssertions,null,2),enabled:true});dialog.value=true;void loadSourceInterfaces()}
async function save(){if(isSystemInput.value&&form.source_interfaces.length===0){ElMessage.error('请选择至少一个接口');return}if(!await formRef.value?.validate().catch(()=>false))return;saving.value=true;try{const taskInterfaceName=form.name.trim();const payload=isSystemInput.value?{source_interface:form.source_interfaces[0]||null,source_interface_ids:form.source_interfaces,name:taskInterfaceName,method:form.method,path:form.path.trim(),module_name:'',api_type:'系统录入',description:form.description,headers:JSON.parse(form.headersText||'{}'),request_params:JSON.parse(form.requestParamsText||'{}'),assertions:JSON.parse(form.assertionsText||'{}'),enabled:form.enabled}:{source_interface:null,source_interface_ids:[],name:taskInterfaceName,method:form.method,path:form.path.trim(),module_name:'',api_type:taskInterfaceName,description:form.description,headers:JSON.parse(form.headersText||'{}'),request_params:JSON.parse(form.requestParamsText||'{}'),assertions:JSON.parse(form.assertionsText||'{}'),enabled:form.enabled};form.id?await api.updateMonitorInterface(form.id,payload):await api.createMonitorInterface(payload);dialog.value=false;await load();ElMessage.success('监控接口保存成功')}catch(e){ElMessage.error((e as Error).message)}finally{saving.value=false}}
async function toggle(item:MonitorApiConfig){try{await api.toggleMonitorInterface(item.id,item.enabled);ElMessage.success(item.enabled?'已启用':'已停用')}catch(e){item.enabled=!item.enabled;ElMessage.error((e as Error).message)}}
async function remove(item:MonitorApiConfig){try{await ElMessageBox.confirm(`确定删除监控接口“${item.name}”吗？`,'删除监控接口',{type:'warning'});await api.deleteMonitorInterface(item.id);await load();ElMessage.success('监控接口已删除')}catch(e){if(e!=='cancel')ElMessage.error((e as Error).message)}}
function formatTime(value:string){return dayjs(value).format('YYYY-MM-DD HH:mm:ss')}
let removeOverflowTooltip=()=>{}
onMounted(()=>{removeOverflowTooltip=installOverflowTooltip();void load()})
onUnmounted(()=>removeOverflowTooltip())
</script>
