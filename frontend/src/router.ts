import { createRouter, createWebHistory } from 'vue-router'
import { auth } from './auth'

const router = createRouter({ history:createWebHistory(), routes:[
  {path:'/login',component:()=>import('./views/LoginView.vue'),meta:{public:true}},
  {path:'/',component:()=>import('./layout/AppLayout.vue'),children:[
    {path:'',name:'home',component:()=>import('./views/HomeView.vue'),meta:{title:'首页'}},
    {path:'intelligence',redirect:'/intelligence/data-factory'},
    {path:'intelligence/data-factory',name:'intelligence-data-factory',component:()=>import('./views/data-factory/index.vue'),meta:{title:'数据工厂'}},
    {path:'automation',redirect:'/automation/execution'},
    {path:'automation/interface',name:'automation-interface',component:()=>import('./views/InterfaceView.vue'),meta:{title:'接口'}},
    {path:'automation/execution',name:'automation-execution',component:()=>import('./views/AutomationView.vue'),meta:{title:'执行'}},
    {path:'monitor',redirect:'/monitor/interfaces'},
    {path:'monitor/interfaces',name:'monitor-interfaces',component:()=>import('./views/MonitorInterfaceView.vue'),meta:{title:'接口管理'}},
    {path:'monitor/tasks',name:'monitor-tasks',component:()=>import('./views/MonitorTaskView.vue'),meta:{title:'任务管理'}},
    {path:'monitor/alarms',name:'monitor-alarms',component:()=>import('./views/MonitorAlarmView.vue'),meta:{title:'报警记录'}},
    {path:'settings',redirect:'/settings/environment'},
    {path:'settings/environment',name:'settings-environment',component:()=>import('./views/SettingsView.vue'),meta:{title:'环境配置'}},
    {path:'settings/users',name:'settings-users',component:()=>import('./views/SettingsView.vue'),meta:{title:'用户管理'}},
    {path:'settings/roles',name:'settings-roles',component:()=>import('./views/SettingsView.vue'),meta:{title:'角色管理'}},
  ]},
  {path:'/:pathMatch(.*)*',redirect:'/'},
]})
router.beforeEach(to => { if (!to.meta.public && !auth.token) return '/login'; if (to.path === '/login' && auth.token) return '/' })
router.afterEach(to => { document.title = `${String(to.meta.title || '登录')} · AIBET Auto` })
export default router
