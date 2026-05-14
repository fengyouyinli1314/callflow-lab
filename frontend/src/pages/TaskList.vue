<template>
  <section>
    <div class="page-header">
      <div>
        <h1>评测任务</h1>
        <p>管理复杂任务指令、目标场景和评测目标。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openCreate">新增任务</el-button>
    </div>

    <div class="panel">
      <el-table :data="tasks" v-loading="loading">
        <el-table-column prop="name" label="任务名称" min-width="190" />
        <el-table-column prop="target_scenario" label="场景" width="150" />
        <el-table-column prop="evaluation_goal" label="评测目标" min-width="260" show-overflow-tooltip />
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :icon="View" @click="$router.push(`/tasks/${row.id}`)">查看</el-button>
            <el-button size="small" :icon="Edit" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" type="danger" :icon="Delete" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="editing ? '编辑任务' : '新增任务'" width="680px">
      <el-form label-position="top">
        <el-form-item label="任务名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="任务描述"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item label="目标场景"><el-input v-model="form.target_scenario" /></el-form-item>
        <el-form-item label="复杂任务指令"><el-input v-model="form.system_instruction" type="textarea" :rows="3" /></el-form-item>
        <el-form-item label="评测目标"><el-input v-model="form.evaluation_goal" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :icon="Check" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, Delete, Edit, Plus, View } from '@element-plus/icons-vue'
import request from '../api/request'

const tasks = ref([])
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const emptyForm = () => ({ name: '', description: '', target_scenario: '', system_instruction: '', evaluation_goal: '' })
const form = reactive(emptyForm())

const load = async () => {
  loading.value = true
  try {
    tasks.value = await request.get('/api/tasks')
  } finally {
    loading.value = false
  }
}

const assignForm = (data) => Object.assign(form, emptyForm(), data || {})
const openCreate = () => {
  editing.value = null
  assignForm()
  dialogVisible.value = true
}
const openEdit = (row) => {
  editing.value = row
  assignForm(row)
  dialogVisible.value = true
}
const save = async () => {
  if (editing.value) {
    await request.put(`/api/tasks/${editing.value.id}`, form)
  } else {
    await request.post('/api/tasks', form)
  }
  ElMessage.success('已保存')
  dialogVisible.value = false
  load()
}
const remove = async (row) => {
  await ElMessageBox.confirm(`确认删除“${row.name}”？`, '删除任务')
  await request.delete(`/api/tasks/${row.id}`)
  ElMessage.success('已删除')
  load()
}

onMounted(load)
</script>
