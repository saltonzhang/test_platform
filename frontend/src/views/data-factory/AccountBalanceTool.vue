<template>
  <el-drawer v-model="visible" title="账户余额" size="min(620px, 92vw)">
    <div class="data-factory-detail">
      <div class="data-factory-detail-head"><span class="data-factory-icon blue"><el-icon><WalletFilled/></el-icon></span><div><h3>账户余额</h3><p>使用当前系统用户的后台账号登录，按邮箱查询会员后创建并审批 CASH 加款单。</p></div></div>
      <el-alert title="该操作会直接创建并审批加款单据" type="warning" :closable="false" show-icon/>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="运行环境" prop="environment"><el-select v-model="form.environment" placeholder="请选择后台环境" style="width:100%"><el-option v-for="env in backendEnvironments" :key="env.id" :label="env.name" :value="env.id"/></el-select></el-form-item>
        <el-form-item label="会员邮箱" prop="email"><el-input v-model="form.email" placeholder="请输入会员邮箱"/></el-form-item>
        <el-form-item label="加款金额（Cash）" prop="amount"><el-input-number v-model="form.amount" :min="0.01" :max="1000000" :precision="2" controls-position="right" style="width:100%"/></el-form-item>
        <el-form-item label="当前平台密码" prop="login_password"><el-input v-model="form.login_password" type="password" show-password autocomplete="current-password"/></el-form-item>
      </el-form>
      <el-button type="primary" :loading="submitting" @click="submit">创建并审批加款</el-button>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed,reactive,ref,watch } from 'vue'
import { ElMessage,ElMessageBox,type FormInstance,type FormRules } from 'element-plus'
import { WalletFilled } from '@element-plus/icons-vue'
import * as api from '@/api'
import type { Environment } from '@/types'

const visible=defineModel<boolean>({default:false})
const props=defineProps<{environments:Environment[]}>()
const emit=defineEmits<{executed:[]}>()
const submitting=ref(false),formRef=ref<FormInstance>()
const form=reactive({environment:0,email:'',amount:0,login_password:''})
const rules:FormRules={environment:[{required:true,message:'请选择后台环境'}],email:[{required:true,message:'请输入会员邮箱'},{type:'email',message:'邮箱格式不正确'}],amount:[{required:true,message:'请输入加款金额'}],login_password:[{required:true,message:'请输入当前平台密码'}]}
const backendEnvironments=computed(()=>props.environments.filter(item=>item.login_url.includes('/api/v2/login')))
watch(backendEnvironments,environments=>{if(environments.length&&!environments.some(item=>item.id===form.environment))form.environment=environments[0].id},{immediate:true})

async function submit(){if(!await formRef.value?.validate().catch(()=>false))return;try{await ElMessageBox.confirm(`确认向 ${form.email} 加款 ${form.amount} Cash 并直接审批吗？`,'确认账户余额操作',{type:'warning',confirmButtonText:'确认执行'});submitting.value=true;await api.executeAccountBalance({...form});form.login_password='';ElMessage.success('加款单据已创建并审批');visible.value=false;emit('executed')}catch(error){if(error!=='cancel')ElMessage.error((error as Error).message)}finally{submitting.value=false}}

</script>
