import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './style.css'
import App from './App.vue'
import { router } from './router'

/**
 * main.ts
 *
 * 前端应用入口文件。
 *
 * 作用：
 * 1. 创建 Vue 应用实例；
 * 2. 注册 Pinia 状态管理；
 * 3. 注册 Vue Router 路由；
 * 4. 注册 Element Plus UI 组件库；
 * 5. 引入全局浅色后台主题样式 style.css。
 *
 * 注意：
 * - 这里不写业务逻辑；
 * - 业务状态放在 src/stores；
 * - 页面路由放在 src/router；
 * - 接口请求放在 src/api。
 */
const app = createApp(App)

/** 注册 Pinia，全局 Store 才能在页面和组件中使用。 */
app.use(createPinia())

/** 注册路由，页面才能通过 /dashboard、/chat 等路径访问。 */
app.use(router)

/** 注册 Element Plus，项目中的 el-button、el-table、el-tag 等组件来自这里。 */
app.use(ElementPlus)

/** 挂载到 index.html 中的 <div id="app"></div>。 */
app.mount('#app')
