<template>
  <el-config-provider namespace="el">
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-mark">CF</div>
          <div>
            <strong>callflow-lab</strong>
            <span>复杂外呼任务对话模型自动评测平台</span>
          </div>
        </div>
        <nav class="nav">
          <RouterLink to="/dashboard"><DataLine />数据大屏</RouterLink>
          <RouterLink to="/tasks"><Document />评测任务</RouterLink>
          <RouterLink to="/cases"><Tickets />测试用例</RouterLink>
          <RouterLink to="/runs"><VideoPlay />开始评测</RouterLink>
          <RouterLink to="/batch-runs"><Operation />批量评测</RouterLink>
          <RouterLink to="/model-config"><Setting />模型配置</RouterLink>
        </nav>
      </aside>
      <main class="main-view">
        <RouterView />
      </main>
    </div>
  </el-config-provider>
</template>
