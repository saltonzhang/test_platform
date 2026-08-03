<template>
  <div class="shell">
    <aside :class="['sidebar',{collapsed}]">
      <div class="brand"><span class="brand-mark">A</span><div><b>AIBET</b><small>智能自动化平台</small></div></div>
      <nav>
        <router-link v-if="hasPermission('home.view')" to="/"><el-icon><HomeFilled /></el-icon><span>首页</span></router-link>
        <div v-if="hasPermission('data_factory.view')||hasPermission('data_factory.account_balance')||hasPermission('data_factory.account_add')||hasPermission('data_factory.order_result_push')" :class="['nav-group',{open:expandedGroups.intelligence}]">
          <button class="nav-parent" :class="{active:route.path.startsWith('/intelligence')}" type="button" :aria-expanded="expandedGroups.intelligence" aria-controls="intelligence-menu" @click="toggleGroup('intelligence')"><el-icon><MagicStick /></el-icon><span>智能工具</span><el-icon class="nav-arrow"><ArrowRight /></el-icon></button>
          <div id="intelligence-menu" class="nav-children">
            <strong class="nav-flyout-title">智能工具</strong>
            <router-link to="/intelligence/data-factory"><span>数据工厂</span></router-link>
          </div>
        </div>
        <div v-if="hasPermission('automation.view')" :class="['nav-group',{open:expandedGroups.automation}]">
          <button class="nav-parent" :class="{active:route.path.startsWith('/automation')}" type="button" :aria-expanded="expandedGroups.automation" aria-controls="automation-menu" @click="toggleGroup('automation')"><el-icon><Calendar /></el-icon><span>自动化</span><el-icon class="nav-arrow"><ArrowRight /></el-icon></button>
          <div id="automation-menu" class="nav-children">
            <strong class="nav-flyout-title">自动化</strong>
            <router-link to="/automation/interface"><span>接口</span></router-link>
            <router-link to="/automation/execution"><span>执行</span></router-link>
          </div>
        </div>
        <div v-if="hasAnyPermission(['monitor.api.view','monitor.task.view','monitor.alarm.view'])" :class="['nav-group',{open:expandedGroups.monitor}]">
          <button class="nav-parent" :class="{active:route.path.startsWith('/monitor')}" type="button" :aria-expanded="expandedGroups.monitor" aria-controls="monitor-menu" @click="toggleGroup('monitor')"><el-icon><Monitor /></el-icon><span>监控中心</span><el-icon class="nav-arrow"><ArrowRight /></el-icon></button>
          <div id="monitor-menu" class="nav-children">
            <strong class="nav-flyout-title">监控中心</strong>
            <router-link v-if="hasPermission('monitor.api.view')" to="/monitor/interfaces"><span>接口管理</span></router-link>
            <router-link v-if="hasPermission('monitor.task.view')" to="/monitor/tasks"><span>任务管理</span></router-link>
            <router-link v-if="hasPermission('monitor.alarm.view')" to="/monitor/alarms"><span>报警记录</span></router-link>
          </div>
        </div>
        <div v-if="hasAnyPermission(['environment.view','users.view','roles.view'])" :class="['nav-group',{open:expandedGroups.settings}]">
          <button class="nav-parent" :class="{active:route.path.startsWith('/settings')}" type="button" :aria-expanded="expandedGroups.settings" aria-controls="settings-menu" @click="toggleGroup('settings')"><el-icon><Setting /></el-icon><span>配置</span><el-icon class="nav-arrow"><ArrowRight /></el-icon></button>
          <div id="settings-menu" class="nav-children">
            <strong class="nav-flyout-title">配置</strong>
            <router-link v-if="hasPermission('environment.view')" to="/settings/environment"><span>环境配置</span></router-link>
            <router-link v-if="hasPermission('users.view')" to="/settings/users"><span>用户管理</span></router-link>
            <router-link v-if="hasPermission('roles.view')" to="/settings/roles"><span>角色管理</span></router-link>
          </div>
        </div>
      </nav>
      <div class="sidebar-foot"><div class="online"><i></i><span>系统运行正常</span></div><button @click="collapsed=!collapsed"><el-icon><DArrowLeft /></el-icon><span>收起导航</span></button></div>
    </aside>
    <main :class="{expanded:collapsed}">
      <header>
        <div class="page-breadcrumb">{{ breadcrumb }}</div>
        <div class="header-right"><el-button circle><el-icon><Bell /></el-icon></el-button><el-dropdown @command="logout"><span class="profile"><b>{{ auth.user?.name?.slice(0,1) }}</b><i>{{ auth.user?.name }}<small>{{ auth.user?.role_name }}</small></i><el-icon><ArrowDown /></el-icon></span><template #dropdown><el-dropdown-menu><el-dropdown-item command="logout">退出登录</el-dropdown-item></el-dropdown-menu></template></el-dropdown></div>
      </header>
      <div class="page-content"><router-view /></div>
    </main>
  </div>
</template>
<script setup lang="ts">
import { computed,reactive,ref,watch } from 'vue'; import { useRoute,useRouter } from 'vue-router'; import { auth,clearAuth,hasPermission } from '@/auth'
type NavGroup='intelligence'|'automation'|'monitor'|'settings'
const route=useRoute(),router=useRouter(),collapsed=ref(false)
const expandedGroups=reactive<Record<NavGroup,boolean>>({intelligence:route.path.startsWith('/intelligence'),automation:route.path.startsWith('/automation'),monitor:route.path.startsWith('/monitor'),settings:route.path.startsWith('/settings')})
const breadcrumb=computed(()=>route.path==='/intelligence/data-factory'?'智能工具 / 数据工厂':route.path==='/automation/interface'?'自动化 / 接口':route.path==='/automation/execution'?'自动化 / 执行':route.path==='/monitor/interfaces'?'监控中心 / 接口管理':route.path==='/monitor/tasks'?'监控中心 / 任务管理':route.path==='/monitor/alarms'?'监控中心 / 报警记录':route.path==='/settings/environment'?'配置 / 环境配置':route.path==='/settings/users'?'配置 / 用户管理':route.path==='/settings/roles'?'配置 / 角色管理':'首页')
function groupForPath(path:string):NavGroup|undefined{return path.startsWith('/intelligence')?'intelligence':path.startsWith('/automation')?'automation':path.startsWith('/monitor')?'monitor':path.startsWith('/settings')?'settings':undefined}
function hasAnyPermission(codes:string[]){return codes.some(hasPermission)}
function toggleGroup(group:NavGroup){if(collapsed.value){collapsed.value=false;expandedGroups[group]=true;return}expandedGroups[group]=!expandedGroups[group]}
watch(()=>route.path,path=>{const group=groupForPath(path);if(group)expandedGroups[group]=true})
const logout=()=>{clearAuth();void router.push('/login')}
</script>
