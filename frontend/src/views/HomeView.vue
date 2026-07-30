<template>
  <div v-loading="loading">
    <div class="welcome">
      <div><span>{{todayText}}</span><h2>你好，{{auth.user?.name}}</h2><p>接口资产与自动化执行数据概览</p></div>
    </div>
    <div class="metrics">
      <article v-for="item in metrics" :key="item.label"><div :class="['metric-icon',item.tone]"><el-icon><component :is="item.icon"/></el-icon></div><span>{{item.label}}</span><b>{{item.value}}</b><small>{{item.note}}</small></article>
    </div>
    <div class="dashboard-data-grid">
      <section class="surface dashboard-panel">
        <div class="section-head"><div><h3>接口数据</h3><p>接口请求方式与业务模块分布</p></div><el-button link type="primary" @click="$router.push('/automation/interface')">查看接口</el-button></div>
        <div class="method-summary"><div v-for="item in stats?.interfaces.by_method" :key="item.method"><span>{{item.method}}</span><b>{{item.count}}</b></div></div>
        <div class="distribution-list"><div v-for="item in stats?.interfaces.by_module" :key="item.module_name"><span>{{item.module_name}}</span><el-progress :percentage="modulePercentage(item.count)" :show-text="false"/><b>{{item.count}}</b></div></div>
      </section>
      <section class="surface dashboard-panel">
        <div class="section-head"><div><h3>执行数据</h3><p>任务及接口明细执行情况</p></div></div>
        <div class="execution-summary"><div><span>任务通过</span><b>{{stats?.execution.task_passed||0}}</b></div><div><span>任务失败</span><b class="danger-text">{{stats?.execution.task_failed||0}}</b></div><div><span>接口明细</span><b>{{stats?.execution.detail_total||0}}</b></div><div><span>平均耗时</span><b>{{stats?.execution.average_duration_ms||0}} ms</b></div></div>
        <div class="trend-bars"><div v-for="item in stats?.trend" :key="item.date"><div class="trend-stack"><i class="passed" :style="{height:barHeight(item.passed)}"></i><i class="failed" :style="{height:barHeight(item.failed)}"></i></div><span>{{dayLabel(item.date)}}</span></div></div>
        <div class="trend-legend"><span><i class="passed"></i>通过</span><span><i class="failed"></i>失败</span></div>
      </section>
    </div>
    <section class="surface recent">
      <div class="section-head"><div><h3>最近执行任务</h3><p>按更新时间展示最新任务</p></div><el-button link type="primary" @click="$router.push('/automation/execution')">查看全部</el-button></div>
      <el-table class="recent-tasks-table" :data="stats?.recent_tasks||[]" empty-text="暂无执行任务"><el-table-column prop="name" label="任务名称" min-width="140" show-overflow-tooltip/><el-table-column prop="module_name" label="模块" min-width="180" show-overflow-tooltip/><el-table-column prop="environment_name" label="环境" width="120"/><el-table-column prop="owner_name" label="负责人" width="110"/><el-table-column label="状态" width="100"><template #default="{row}"><el-tag :type="statusType(row.status)">{{row.status_name}}</el-tag></template></el-table-column><el-table-column label="更新时间" width="160"><template #default="{row}">{{formatTime(row.updated_at)}}</template></el-table-column></el-table>
    </section>
  </div>
</template>
<script setup lang="ts">
import {computed,onMounted,ref} from 'vue';import dayjs from 'dayjs';import {ElMessage} from 'element-plus';import {auth} from '@/auth';import * as api from '@/api';import type {DashboardStats} from '@/types'
const loading=ref(false),stats=ref<DashboardStats|null>(null)
const todayText=dayjs().format('YYYY年M月D日')
const metrics=computed(()=>[{label:'接口总数',value:stats.value?.interfaces.total||0,note:`今日执行 ${stats.value?.execution.today_total||0} 次`,icon:'Connection',tone:'blue'},{label:'执行任务',value:stats.value?.execution.task_total||0,note:`执行中 ${stats.value?.execution.task_running||0} 个`,icon:'VideoPlay',tone:'amber'},{label:'接口通过率',value:`${stats.value?.execution.pass_rate||0}%`,note:`通过 ${stats.value?.execution.detail_passed||0} 条`,icon:'CircleCheckFilled',tone:'green'},{label:'失败明细',value:stats.value?.execution.detail_failed||0,note:'累计失败接口执行',icon:'WarningFilled',tone:'red'}])
const maxTrend=computed(()=>Math.max(1,...(stats.value?.trend.map(item=>item.passed+item.failed)||[1])))
function modulePercentage(count:number){return stats.value?.interfaces.total?Math.round(count*100/stats.value.interfaces.total):0}function barHeight(value:number){return `${Math.max(value?5:0,Math.round(value*100/maxTrend.value))}%`}function dayLabel(value:string){return dayjs(value).format('MM/DD')}function formatTime(value:string){return dayjs(value).format('YYYY-MM-DD HH:mm')}function statusType(value:string){return value==='passed'?'success':value==='failed'?'danger':value==='running'?'primary':'info'}
onMounted(async()=>{loading.value=true;try{stats.value=(await api.getDashboard()).data}catch(e){ElMessage.error((e as Error).message)}finally{loading.value=false}})
</script>
