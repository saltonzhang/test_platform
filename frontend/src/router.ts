import { createRouter, createWebHistory } from 'vue-router'
import { auth, hasPermission } from './auth'

const router = createRouter({ history:createWebHistory(), routes:[
  {path:'/login',component:()=>import('./views/LoginView.vue'),meta:{public:true}},
  {path:'/',component:()=>import('./layout/AppLayout.vue'),children:[
    {path:'',name:'home',component:()=>import('./views/HomeView.vue'),meta:{title:'首页'}},
    {path:'intelligence',redirect:'/intelligence/data-factory'},
    {path:'intelligence/data-factory',name:'intelligence-data-factory',component:()=>import('./views/data-factory/index.vue'),meta:{title:'数据工厂'}},
    {path:'automation',redirect:'/automation/execution'},
    {path:'automation/interface',name:'automation-interface',component:()=>import('./views/InterfaceView.vue'),meta:{title:'接口'}},
    {path:'automation/execution',name:'automation-execution',component:()=>import('./views/AutomationView.vue'),meta:{title:'执行'}},
    {path:'testcase',redirect:'/testcase/packages'},
    {path:'testcase/packages',name:'testcase-packages',component:()=>import('./views/TestCasePackageView.vue'),meta:{title:'用例包'}},
    {path:'testcase/packages/:id/edit',name:'testcase-package-editor',component:()=>import('./views/TestCasePackageEditor.vue'),meta:{title:'在线编辑用例包'}},
    {path:'testcase/execution',name:'testcase-execution',component:()=>import('./views/TestCaseExecutionView.vue'),meta:{title:'用例执行'}},
    {path:'monitor',redirect:'/monitor/interfaces'},
    {path:'monitor/interfaces',name:'monitor-interfaces',component:()=>import('./views/MonitorInterfaceView.vue'),meta:{title:'任务包'}},
    {path:'monitor/tasks',name:'monitor-tasks',component:()=>import('./views/MonitorTaskView.vue'),meta:{title:'任务管理'}},
    {path:'monitor/alarms',name:'monitor-alarms',component:()=>import('./views/MonitorAlarmView.vue'),meta:{title:'告警记录'}},
    {path:'settings',redirect:'/settings/environment'},
    {path:'settings/environment',name:'settings-environment',component:()=>import('./views/SettingsView.vue'),meta:{title:'环境配置'}},
    {path:'settings/users',name:'settings-users',component:()=>import('./views/SettingsView.vue'),meta:{title:'用户管理'}},
    {path:'settings/roles',name:'settings-roles',component:()=>import('./views/SettingsView.vue'),meta:{title:'角色管理'}},
  ]},
  {path:'/:pathMatch(.*)*',redirect:'/'},
]})
const dataFactoryPermissions=['data_factory.view','data_factory.account_add','data_factory.account_balance','data_factory.member_status_activate','data_factory.member_query','data_factory.order_result_push','data_factory.rollback_settlement','data_factory.bet_cancel','data_factory.rollback_bet_cancel']
function canAccessPage(path:string){
  if(path==='/')return hasPermission('home.view')
  if(path.startsWith('/intelligence'))return dataFactoryPermissions.some(hasPermission)
  if(path.startsWith('/automation'))return hasPermission('automation.view')
  if(path==='/testcase/packages'||path.startsWith('/testcase/packages/'))return path==='/testcase/packages/new/edit'?hasPermission('testcase.package.create'):hasPermission(path.endsWith('/edit')?'testcase.package.edit':'testcase.package.view')
  if(path==='/testcase/execution')return hasPermission('testcase.execution.view')
  const permissions:[string,string][]=[['/monitor/interfaces','monitor.api.view'],['/monitor/tasks','monitor.task.view'],['/monitor/alarms','monitor.alarm.view'],['/settings/environment','environment.view'],['/settings/users','users.view'],['/settings/roles','roles.view']]
  const required=permissions.find(([route])=>path===route)?.[1]
  return !required||hasPermission(required)
}
function firstAccessiblePath(){
  return [
    '/',
    '/intelligence/data-factory',
    '/automation/execution',
    '/testcase/packages',
    '/testcase/execution',
    '/monitor/interfaces',
    '/monitor/tasks',
    '/monitor/alarms',
    '/settings/environment',
    '/settings/users',
    '/settings/roles',
  ].find(path=>canAccessPage(path))
}
router.beforeEach(to => {
  if (!to.meta.public && !auth.token) return '/login'
  if (to.path === '/login' && auth.token) return firstAccessiblePath()
  if (!to.meta.public && !canAccessPage(to.path)) return firstAccessiblePath() || '/login'
})
router.afterEach(to => { document.title = `${String(to.meta.title || '登录')} · AIBET Auto` })
export default router
