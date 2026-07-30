<template>
  <el-drawer v-model="visible" title="订单结果推送" size="min(760px, 94vw)">
    <div class="data-factory-detail">
      <div class="data-factory-detail-head"><span class="data-factory-icon green"><el-icon><Promotion/></el-icon></span><div><h3>订单结果推送</h3><p>根据 event_id 生成消息 key，并将订单结算结果推送到 msg_bet_settlement。</p></div></div>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top"><div class="order-result-form">
        <el-form-item label="certainty" prop="certainty"><el-input v-model="form.certainty"/></el-form-item><el-form-item label="product" prop="product"><el-input v-model="form.product"/></el-form-item>
        <el-form-item class="wide" label="event_id" prop="event_id"><el-input v-model="form.event_id" placeholder="例如 sr:match:72827258 或 pn2tgn3bkz5viycygy"/></el-form-item>
        <el-form-item label="market id" prop="market_id"><el-input v-model="form.market_id"/></el-form-item><el-form-item label="specifiers"><el-input v-model="form.specifiers"/></el-form-item>
        <el-form-item label="outcome id" prop="outcome_id"><el-input v-model="form.outcome_id" placeholder="例如 70 或 geya"/></el-form-item><el-form-item label="result" prop="result"><el-input v-model="form.result"/></el-form-item>
        <el-form-item label="void_factor" prop="void_factor"><el-input v-model="form.void_factor"/></el-form-item><el-form-item label="timestamp（毫秒）" prop="timestamp"><el-input-number v-model="form.timestamp" :min="1" :precision="0" controls-position="right" style="width:100%"/></el-form-item>
      </div></el-form>
      <el-button type="primary" :loading="submitting" @click="submit"><el-icon><Promotion/></el-icon>推送订单结果</el-button>
      <el-result v-if="response" icon="success" title="推送成功" :sub-title="`HTTP ${response.status_code} · ${response.message}`"><template #extra><div class="order-result-response"><el-descriptions :column="1" border><el-descriptions-item label="实际 event ID">{{response.event_id}}</el-descriptions-item><el-descriptions-item label="消息 Key">{{response.key}}</el-descriptions-item><el-descriptions-item label="实际 outcome ID">{{response.outcome_id}}</el-descriptions-item><el-descriptions-item label="时间戳">{{response.timestamp}}</el-descriptions-item></el-descriptions><pre>{{response.response||'接口未返回响应正文'}}</pre></div></template></el-result>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { reactive,ref,watch } from 'vue'
import { ElMessage,type FormInstance,type FormRules } from 'element-plus'
import { Promotion } from '@element-plus/icons-vue'
import * as api from '@/api'
import type { OrderResultPushResult } from '@/types'
const visible=defineModel<boolean>({default:false})
const emit=defineEmits<{executed:[]}>()
const submitting=ref(false),formRef=ref<FormInstance>(),response=ref<OrderResultPushResult>()
const form=reactive({certainty:'2',product:'1',event_id:'',market_id:'',specifiers:'',outcome_id:'',result:'0',void_factor:'0',timestamp:Date.now()})
const rules:FormRules={certainty:[{required:true,message:'请输入 certainty'}],product:[{required:true,message:'请输入 product'}],event_id:[{required:true,message:'请输入 event_id'}],market_id:[{required:true,message:'请输入 market id'}],outcome_id:[{required:true,message:'请输入 outcome id'}],result:[{required:true,message:'请输入 result'}],void_factor:[{required:true,message:'请输入 void_factor'}],timestamp:[{required:true,message:'请输入毫秒时间戳'}]}
watch(visible,isVisible=>{if(isVisible){form.timestamp=Date.now();response.value=undefined}})
async function submit(){if(!await formRef.value?.validate().catch(()=>false))return;submitting.value=true;try{const result=await api.pushOrderResult(form);response.value=result.data;emit('executed');ElMessage.success('订单结果推送成功')}catch(error){ElMessage.error((error as Error).message)}finally{submitting.value=false}}
</script>
