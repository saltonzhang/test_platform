<template>
  <main class="login-page"><section class="login-aside"><div class="login-brand"><span>A</span><b>AIBET Auto</b></div><div><small>AI TEST AUTOMATION</small><h1>让每一次发布<br>都有据可依</h1><p>统一管理自动化任务、环境配置与平台权限，持续交付更可靠的软件。</p></div></section><section class="login-form-wrap"><div class="login-form"><div class="mobile-brand">AIBET Auto</div><h2>欢迎回来</h2><template v-if="!passwordLogin"><p>请使用 Lark 账号免密登录</p><el-button type="primary" size="large" :loading="loading" @click="loginWithLark">Lark 免密登录</el-button><el-button text @click="showPasswordLogin">账号密码登录</el-button></template><el-form v-else ref="formRef" :model="form" :rules="rules" @submit.prevent="submitPasswordLogin"><p>使用平台账号登录</p><el-form-item prop="username"><label>登录账号</label><el-input v-model="form.username" size="large" autocomplete="username" placeholder="请输入账号" /></el-form-item><el-form-item prop="password"><label>登录密码</label><el-input v-model="form.password" size="large" type="password" show-password autocomplete="current-password" placeholder="请输入密码" @keyup.enter="submitPasswordLogin" /></el-form-item><el-button type="primary" size="large" native-type="submit" :loading="loading" style="width:100%">登录平台</el-button><el-button text @click="passwordLogin=false">返回 Lark 登录</el-button></el-form><p v-if="errorMessage" class="login-error">{{ errorMessage }}</p></div></section></main>
</template>
<script setup lang="ts">
import { onMounted,reactive,ref } from 'vue';import { useRouter } from 'vue-router';import { ElMessage,type FormInstance,type FormRules } from 'element-plus';import { login } from '@/api';import { setAuth } from '@/auth';import type { User } from '@/types'
const router=useRouter(),formRef=ref<FormInstance>(),loading=ref(false),errorMessage=ref(''),passwordLogin=ref(false),form=reactive({username:'',password:''})
const rules:FormRules={username:[{required:true,message:'请输入登录账号'}],password:[{required:true,message:'请输入登录密码'}]}
function loginWithLark(){loading.value=true;window.location.assign('/api/auth/lark/login/')}
function showPasswordLogin(){errorMessage.value='';passwordLogin.value=true}
async function submitPasswordLogin(){if(!await formRef.value?.validate().catch(()=>false))return;loading.value=true;errorMessage.value='';try{const result=await login(form);setAuth(result.data.access,result.data.refresh,result.data.user);ElMessage.success('登录成功');await router.replace('/')}catch(error){errorMessage.value=(error as Error).message}finally{loading.value=false}}
onMounted(async()=>{const params=new URLSearchParams(window.location.hash.slice(1));const access=params.get('access'),refresh=params.get('refresh'),rawUser=params.get('user');if(access&&refresh&&rawUser){try{setAuth(access,refresh,JSON.parse(rawUser) as User);history.replaceState(null,'',window.location.pathname);await router.replace('/')}catch{errorMessage.value='Lark 登录结果无效，请重新登录'};return}if(new URLSearchParams(window.location.search).get('lk_jump_to_browser')==='true')loginWithLark()})
</script>

<style scoped>
.login-aside { justify-content: flex-start; }
.login-aside > div:nth-child(2) { margin: auto 0; }
</style>
