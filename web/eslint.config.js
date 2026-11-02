/* ============================================================================
 * eslint.config.js — CI JS 段的 lint 面（flat config，ESM）
 * 两面分开配，理由不是口味：
 *   · src/** 与 vite.config.ts 走**类型感知**规则集（recommendedTypeChecked）。
 *     A5 判据要求「一个故意引入的前端漂移能让 CI 红」，其中「未处理的 Promise」这条
 *     只有类型感知规则（no-floating-promises）看得见，纯语法规则集对它完全无感。
 *   · scripts/**\/*.mjs 走**非类型感知**规则集。门禁脚本不在 tsconfig 的 include 里
 *     （它读后端源、不读 DOM 类型），塞进类型感知面会让 project service 报「文件不在
 *     项目内」——那是配置错误，不是脚本的缺陷。
 * ==========================================================================*/
import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**'] },

  // ---- 应用面：TS + Vue，类型感知 ----
  {
    files: ['src/**/*.{ts,vue}', 'vite.config.ts'],
    extends: [js.configs.recommended, ...tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
        // `.vue` 不是 TS 的标准扩展名，不声明这一条 project service 直接不把这些文件
        // 交给规则（症状是每个 .vue 报一条 0:0 的 Parsing error，而不是某个规则红）。
        extraFileExtensions: ['.vue'],
      },
    },
    rules: {
      // 单文件组件的名就是它的职责名，不为满足叠词规则而加前缀遮意图。
      'vue/multi-word-component-names': 'off',
    },
  },

  // ---- Vue 单文件组件的结构规则（模板必须在 vue-eslint-parser 下解析）----
  {
    files: ['src/**/*.vue'],
    extends: [pluginVue.configs['flat/recommended']],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
        extraFileExtensions: ['.vue'],
      },
    },
    rules: {
      'vue/multi-word-component-names': 'off',
    },
  },

  // ---- 门禁脚本面：纯语法，不做类型感知 ----
  {
    files: ['scripts/**/*.mjs'],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
  },
)
