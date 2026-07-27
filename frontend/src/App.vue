<template>
  <router-view />
</template>

<style>
/* ==============================================
   Surgery RAG Agent — 柔和专业医疗风格 CSS 变量
   方案 B：暖杏蓝 | DESIGN_SPEC.md 第 10 节
   ============================================== */

:root {
  /* ===== 主色系 ===== */
  --color-primary: hsl(200, 65%, 40%);
  --color-primary-light: hsl(200, 65%, 92%);
  --color-primary-hover: hsl(200, 65%, 35%);
  --color-primary-active: hsl(200, 65%, 30%);
  --color-accent: hsl(25, 55%, 52%);
  --color-accent-light: hsl(25, 55%, 93%);

  /* ===== 背景 ===== */
  --bg-canvas: hsl(40, 15%, 98%);
  --bg-surface: #ffffff;
  --bg-sidebar: hsl(200, 10%, 95%);
  --bg-input: hsl(200, 10%, 97%);
  --bg-hover: hsl(200, 15%, 93%);

  /* ===== 文字 ===== */
  --text-primary: hsl(210, 18%, 18%);
  --text-secondary: hsl(210, 6%, 45%);
  --text-disabled: hsl(210, 4%, 62%);
  --text-link: hsl(200, 65%, 40%);

  /* ===== 语义 ===== */
  --color-success: hsl(155, 50%, 40%);
  --color-warning: hsl(38, 70%, 48%);
  --color-danger: hsl(0, 60%, 48%);
  --color-danger-soft: hsl(0, 55%, 55%);

  /* ===== 边框 ===== */
  --border-default: hsl(210, 8%, 88%);
  --border-light: hsl(210, 10%, 93%);
  --border-focus: hsl(200, 65%, 40%);

  /* ===== 阴影 ===== */
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.04);
  --shadow-md: 0 2px 8px rgba(0, 0, 0, 0.04);
  --shadow-lg: 0 4px 16px rgba(0, 0, 0, 0.06);
  --focus-ring: 0 0 0 3px hsla(200, 65%, 40%, 0.2);

  /* ===== 圆角 ===== */
  --radius-pill: 9999px;
  --radius-card: 12px;
  --radius-input: 10px;
  --radius-bubble: 16px;
  --radius-item: 8px;

  /* ===== 间距（4px 基数） ===== */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;
  --space-10: 40px;
  --space-12: 48px;
  --space-16: 64px;

  /* ===== 排版 ===== */
  --font-sans: "Inter", "PingFang SC", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --font-mono: "JetBrains Mono", "SF Mono", Consolas, monospace;
  --text-xs: 13px;
  --text-sm: 14px;
  --text-base: 16px;
  --text-md: 18px;
  --text-lg: 22px;
  --text-xl: 28px;
  --text-2xl: 36px;

  /* ===== 动效 ===== */
  --ease-standard: cubic-bezier(0.2, 0, 0.8, 1);
  --duration-fast: 150ms;
  --duration-normal: 250ms;
  --duration-slow: 300ms;

  /* ===== 布局 ===== */
  --topbar-height: 56px;
  --sidebar-width: 260px;
  --sidebar-collapsed: 64px;
  --content-max-width: 880px;
}

/* ===== 全局重置 ===== */
*,
*::before,
*::after {
  box-sizing: border-box;
}

html,
body,
#app {
  margin: 0;
  padding: 0;
  min-height: 100vh;
  background: var(--bg-canvas);
  color: var(--text-primary);
  font-family: var(--font-sans);
  font-size: var(--text-base);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* ===== Element Plus 全局覆盖 ===== */

/* 主按钮 */
.el-button--primary {
  --el-button-bg-color: var(--color-primary);
  --el-button-border-color: var(--color-primary);
  --el-button-hover-bg-color: var(--color-primary-hover);
  --el-button-hover-border-color: var(--color-primary-hover);
  --el-button-active-bg-color: var(--color-primary-active);
  --el-button-active-border-color: var(--color-primary-active);
}

/* 成功按钮 */
.el-button--success {
  --el-button-bg-color: var(--color-success);
  --el-button-border-color: var(--color-success);
}

/* 危险按钮 */
.el-button--danger {
  --el-button-bg-color: var(--color-danger);
  --el-button-border-color: var(--color-danger);
}

/* 文字按钮 */
.el-button.is-text {
  color: var(--text-secondary);
}
.el-button.is-text:hover {
  color: var(--text-primary);
  background: var(--bg-hover);
}

/* 输入框 */
.el-input__wrapper {
  border-radius: var(--radius-input);
  box-shadow: 0 0 0 1px var(--border-default) inset;
}
.el-input__wrapper:hover {
  box-shadow: 0 0 0 1px var(--text-disabled) inset;
}
.el-input.is-focus .el-input__wrapper {
  box-shadow: 0 0 0 1px var(--border-focus) inset, var(--focus-ring);
}

/* 标签 */
.el-tag--small {
  border-radius: var(--radius-item);
}

/* 抽屉 */
.el-drawer__header {
  padding: var(--space-5) var(--space-6);
  border-bottom: 1px solid var(--border-default);
}

/* 对话框 */
.el-message-box {
  border-radius: var(--radius-card);
}

/* 下拉菜单 */
.el-dropdown-menu {
  border-radius: var(--radius-card);
  border: 1px solid var(--border-default);
  box-shadow: var(--shadow-lg);
}

/* 滚动条 */
::-webkit-scrollbar {
  width: 6px;
}
::-webkit-scrollbar-track {
  background: transparent;
}
::-webkit-scrollbar-thumb {
  background: var(--border-default);
  border-radius: 3px;
}
::-webkit-scrollbar-thumb:hover {
  background: var(--text-disabled);
}

/* 动效偏好 */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
</style>
