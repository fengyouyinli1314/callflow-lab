<template>
  <section>
    <div class="page-header">
      <div>
        <h1>模型配置</h1>
        <p>查看被测模型 provider 接入状态；mock_fallback 仅作本地兜底，API Key 只在后端环境变量中配置。</p>
      </div>
      <el-button :icon="Refresh" @click="loadProviders">刷新</el-button>
    </div>

    <div class="panel">
      <div class="panel-title">
        <h2>Provider 列表</h2>
        <span class="muted">不展示 API Key 明文</span>
      </div>
      <el-table :data="providers" v-loading="loading">
        <el-table-column prop="name" label="provider 名称" min-width="160" />
        <el-table-column prop="type" label="provider 类型" width="170" />
        <el-table-column label="当前是否启用" width="160">
          <template #default="{ row }">
            <div class="status-tags">
              <el-tag :type="row.enabled ? 'success' : 'info'">{{ row.enabled ? '已启用' : '未配置' }}</el-tag>
              <el-tag v-if="row.active" type="warning">当前默认</el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="base_url" label="Base URL" min-width="210" show-overflow-tooltip>
          <template #default="{ row }">{{ row.base_url || '-' }}</template>
        </el-table-column>
        <el-table-column prop="model_name" label="Model Name" min-width="150" show-overflow-tooltip />
        <el-table-column prop="endpoint" label="Endpoint" min-width="210" show-overflow-tooltip>
          <template #default="{ row }">{{ row.endpoint || '-' }}</template>
        </el-table-column>
        <el-table-column label="测试连接" width="130" fixed="right">
          <template #default="{ row }">
            <el-button size="small" :icon="Connection" :loading="testing === row.name" @click="testProvider(row)">
              测试
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="grid two provider-notes">
      <div v-for="provider in providers" :key="provider.name" class="panel provider-card">
        <div class="provider-card-head">
          <h2>{{ provider.name }}</h2>
          <el-tag :type="provider.enabled ? 'success' : 'info'">{{ provider.enabled ? '可用' : '需配置' }}</el-tag>
        </div>
        <p>{{ provider.description }}</p>
        <div class="provider-meta">
          <span>类型</span><strong>{{ provider.type }}</strong>
          <span>Model Name</span><strong>{{ provider.model_name || '-' }}</strong>
          <span>API Key</span><strong>{{ provider.api_key_configured ? '已在后端配置' : '未展示 / 未配置' }}</strong>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Connection, Refresh } from '@element-plus/icons-vue'
import request from '../api/request'

const providers = ref([])
const loading = ref(false)
const testing = ref('')

const loadProviders = async () => {
  loading.value = true
  try {
    providers.value = await request.get('/api/model-providers')
  } finally {
    loading.value = false
  }
}

const testProvider = async (provider) => {
  testing.value = provider.name
  try {
    const result = await request.post('/api/model-providers/test', {
      provider: provider.name,
      base_url: provider.base_url,
      model_name: provider.model_name,
      endpoint: provider.endpoint
    })
    const message = result.message || '测试完成'
    if (result.ok) {
      ElMessage.success(message)
    } else {
      ElMessage.warning(message)
    }
  } finally {
    testing.value = ''
  }
}

onMounted(loadProviders)
</script>

<style scoped>
.status-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.provider-notes {
  margin-top: 16px;
}

.provider-card {
  display: grid;
  gap: 12px;
}

.provider-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.provider-card-head h2 {
  margin: 0;
  font-size: 17px;
}

.provider-card p {
  margin: 0;
}

.provider-meta {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  gap: 8px 12px;
}

.provider-meta span {
  color: var(--muted);
  font-size: 12px;
}

.provider-meta strong {
  color: var(--body-text);
  word-break: break-word;
}
</style>
