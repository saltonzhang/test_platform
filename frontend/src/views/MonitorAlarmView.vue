<template>
  <section class="surface monitor-page">
    <div class="monitor-toolbar">
      <el-input v-model="query.keyword" clearable placeholder="搜索任务、接口或报警内容" @input="filterData"/>
      <el-select v-model="query.status" clearable placeholder="全部状态" @change="filterData"><el-option label="未处理" value="open"/><el-option label="已处理" value="handled"/></el-select>
      <el-select v-model="query.level" clearable placeholder="全部级别" @change="filterData"><el-option label="错误" value="error"/><el-option label="警告" value="warning"/></el-select>
      <span>共 {{total}} 条报警</span>
    </div>
    <el-table v-loading="loading" :data="alarms" empty-text="暂无报警记录">
      <el-table-column prop="task_name" label="任务名称" min-width="160"/>
      <el-table-column prop="interface_name" label="接口名称" min-width="150"/>
      <el-table-column label="级别" width="88"><template #default="{row}"><el-tag :type="row.level==='error'?'danger':'warning'">{{row.level_name}}</el-tag></template></el-table-column>
      <el-table-column prop="message" label="报警内容" min-width="320"><template #default="{row}"><span class="danger-text">{{row.message}}</span></template></el-table-column>
      <el-table-column label="状态" width="90"><template #default="{row}"><el-tag :type="row.status==='handled'?'success':'danger'">{{row.status_name}}</el-tag></template></el-table-column>
      <el-table-column label="报警时间" width="155"><template #default="{row}">{{formatTime(row.created_at)}}</template></el-table-column>
      <el-table-column label="处理人" width="110"><template #default="{row}">{{row.handled_by_name||'-'}}</template></el-table-column>
      <el-table-column label="操作" width="150" fixed="right"><template #default="{row}"><el-button link type="primary" @click="openDetail(row)">详情</el-button><el-button v-if="hasPermission('monitor.alarm.handle')" link :type="row.status==='handled'?'warning':'success'" @click="toggleStatus(row)">{{row.status==='handled'?'重新打开':'标记处理'}}</el-button></template></el-table-column>
    </el-table>
    <el-pagination v-model:current-page="query.page" :total="total" :page-size="10" layout="total, prev, pager, next" @current-change="load"/>
  </section>

  <el-drawer v-model="detailVisible" title="报警详情" size="min(760px, 92vw)">
    <template v-if="current">
      <el-descriptions :column="2" border>
        <el-descriptions-item label="任务名称">{{current.task_name}}</el-descriptions-item>
        <el-descriptions-item label="接口名称">{{current.interface_name||'-'}}</el-descriptions-item>
        <el-descriptions-item label="报警级别"><el-tag :type="current.level==='error'?'danger':'warning'">{{current.level_name}}</el-tag></el-descriptions-item>
        <el-descriptions-item label="处理状态"><el-tag :type="current.status==='handled'?'success':'danger'">{{current.status_name}}</el-tag></el-descriptions-item>
        <el-descriptions-item label="报警时间">{{formatTime(current.created_at)}}</el-descriptions-item>
        <el-descriptions-item label="处理时间">{{current.handled_at?formatTime(current.handled_at):'-'}}</el-descriptions-item>
        <el-descriptions-item label="处理人">{{current.handled_by_name||'-'}}</el-descriptions-item>
        <el-descriptions-item label="执行批次">#{{current.execution}}</el-descriptions-item>
      </el-descriptions>
      <div class="alarm-message-box">{{current.message}}</div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { onMounted,onUnmounted,reactive,ref } from 'vue';import { ElMessage } from 'element-plus';import dayjs from 'dayjs';import { hasPermission } from '@/auth';import * as api from '@/api';import { installOverflowTooltip } from '@/overflowTooltip';import type { MonitorAlarm } from '@/types'
const alarms=ref<MonitorAlarm[]>([]),total=ref(0),loading=ref(false),detailVisible=ref(false),current=ref<MonitorAlarm|null>(null),query=reactive({keyword:'',status:'',level:'',page:1})
async function load(){loading.value=true;try{const res=await api.getMonitorAlarms({...query,pageSize:10});alarms.value=res.data.list;total.value=res.data.total}catch(e){ElMessage.error((e as Error).message)}finally{loading.value=false}}
function filterData(){query.page=1;void load()}
function openDetail(row:MonitorAlarm){current.value=row;detailVisible.value=true}
async function toggleStatus(row:MonitorAlarm){if(!hasPermission('monitor.alarm.handle'))return;try{const nextStatus=row.status==='handled'?'open':'handled';await api.updateMonitorAlarm(row.id,{status:nextStatus});await load();ElMessage.success(nextStatus==='handled'?'报警已处理':'报警已重新打开')}catch(e){ElMessage.error((e as Error).message)}}
function formatTime(value:string){return dayjs(value).format('YYYY-MM-DD HH:mm:ss')}
let removeOverflowTooltip=()=>{}
onMounted(()=>{removeOverflowTooltip=installOverflowTooltip();void load()})
onUnmounted(()=>removeOverflowTooltip())
</script>
