<template>
  <el-drawer v-model="visible" title="账户余额" size="min(620px, 92vw)">
    <div class="data-factory-detail">
      <div class="data-factory-detail-head"><span class="data-factory-icon blue"><el-icon><WalletFilled/></el-icon></span><div><h3>账户余额</h3><p>使用平台统一后台账号登录，按邮箱查询会员后创建并审批 CASH 加款单。</p></div></div>
      <el-alert title="该操作会直接创建并审批加款单据" type="warning" :closable="false" show-icon/>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-form-item label="环境包" prop="environment_package"><el-select v-model="form.environment_package" placeholder="请选择包含后台环境的环境包" style="width:100%"><el-option v-for="pkg in backendPackages" :key="pkg.id" :label="pkg.name" :value="pkg.id"/></el-select></el-form-item>
        <el-form-item label="会员邮箱" prop="email"><el-input v-model="form.email" placeholder="请输入会员邮箱"/></el-form-item>
        <el-form-item label="加款金额（Cash）" prop="amount"><el-input-number v-model="form.amount" :min="0.01" :max="1000000" :precision="2" controls-position="right" style="width:100%"/></el-form-item>
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
import type { EnvironmentPackage } from '@/types'

const visible=defineModel<boolean>({default:false})
const props=defineProps<{environmentPackages:EnvironmentPackage[]}>()
const emit=defineEmits<{executed:[]}>()
const submitting=ref(false),formRef=ref<FormInstance>()
const form=reactive({environment_package:0,email:'',amount:0})
const rules:FormRules={environment_package:[{required:true,message:'请选择环境包'}],email:[{required:true,message:'请输入会员邮箱'},{type:'email',message:'邮箱格式不正确'}],amount:[{required:true,message:'请输入加款金额'}]}
const backendPackages=computed(()=>props.environmentPackages)
watch(backendPackages,packages=>{if(packages.length&&!packages.some(item=>item.id===form.environment_package))form.environment_package=packages[0].id},{immediate:true})

async function submit(){if(!await formRef.value?.validate().catch(()=>false))return;try{await ElMessageBox.confirm(`确认向 ${form.email} 加款 ${form.amount} Cash 并直接审批吗？`,'确认账户余额操作',{type:'warning',confirmButtonText:'确认执行'});submitting.value=true;await api.executeAccountBalance({...form});ElMessage.success('加款单据已创建并审批');visible.value=false;emit('executed')}catch(error){if(error!=='cancel')ElMessage.error((error as Error).message)}finally{submitting.value=false}}

</script>
