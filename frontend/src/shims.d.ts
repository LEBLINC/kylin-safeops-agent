/// <reference types="vite/client" />

/**
 * 兼容本地依赖解析差异的声明文件。
 * 正常 npm install 后 element-plus 会提供自己的类型；这里作为兜底，避免部分环境 vue-tsc 解析失败。
 */
// element-plus types provided by package; shim removed

declare module 'element-plus/dist/index.css'
