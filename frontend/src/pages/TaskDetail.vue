<template>
  <section>
    <div class="page-header">
      <div>
        <h1>{{ task.name || '任务详情' }}</h1>
        <p>{{ task.description }}</p>
      </div>
      <el-button :icon="Back" @click="$router.push('/tasks')">返回</el-button>
    </div>

    <div class="grid two">
      <div class="panel">
        <div class="panel-title"><h2>复杂任务指令</h2></div>
        <p class="muted">场景：{{ task.target_scenario }}</p>
        <p>{{ task.system_instruction }}</p>
        <el-divider />
        <p class="muted">评测目标</p>
        <p>{{ task.evaluation_goal }}</p>
      </div>
      <div class="panel">
        <div class="panel-title"><h2>关联测试用例</h2></div>
        <el-table :data="cases">
          <el-table-column prop="name" label="用例" min-width="160" />
          <el-table-column prop="difficulty" label="难度" width="90" />
          <el-table-column prop="max_turns" label="轮数" width="80" />
        </el-table>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Back } from '@element-plus/icons-vue'
import request from '../api/request'

const route = useRoute()
const task = ref({})
const cases = ref([])

onMounted(async () => {
  task.value = await request.get(`/api/tasks/${route.params.id}`)
  cases.value = await request.get(`/api/cases?task_id=${route.params.id}`)
})
</script>
