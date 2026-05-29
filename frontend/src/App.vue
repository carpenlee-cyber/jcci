<template>
  <div id="app">
    <el-container>
      <el-header>
        <div class="header-content">
          <h1>🔗 JCCI 调用链分析平台</h1>
          <el-menu
            :default-active="activeMenu"
            mode="horizontal"
            router
            background-color="#409EFF"
            text-color="#fff"
            active-text-color="#ffd04b"
          >
            <el-menu-item index="/tasks">
              <el-icon><List /></el-icon>
              <span>任务列表</span>
            </el-menu-item>
            <el-menu-item index="/submit">
              <el-icon><Plus /></el-icon>
              <span>提交任务</span>
            </el-menu-item>
          </el-menu>
        </div>
      </el-header>
      
      <el-main>
        <router-view />
      </el-main>
      
      <el-footer>
        <div class="footer-content">
          <p>JCCI Call Chain Analysis Platform | Powered by Vue 3 + FastAPI</p>
        </div>
      </el-footer>
    </el-container>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { List, Plus } from '@element-plus/icons-vue'

const route = useRoute()
const activeMenu = computed(() => route.path)
</script>

<style scoped>
#app {
  height: 100vh;
}

.el-container {
  height: 100%;
}

.el-header {
  background-color: #409EFF;
  padding: 0;
}

.header-content {
  display: flex;
  align-items: center;
  height: 100%;
  padding: 0 20px;
}

.header-content h1 {
  color: white;
  margin-right: 40px;
  font-size: 20px;
}

.el-main {
  padding: 20px;
  background-color: #f5f7fa;
}

.el-footer {
  background-color: #fff;
  border-top: 1px solid #e4e7ed;
  padding: 10px 20px;
}

.footer-content {
  text-align: center;
  color: #909399;
  font-size: 14px;
}
</style>
