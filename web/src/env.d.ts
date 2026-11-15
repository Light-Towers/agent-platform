/* ============================================================================
 * env.d.ts — 构建工具的 ambient 类型入口（本文件只有类型，运行期不存在）
 * 本文件两条声明，各自解决一个**实跑报出来的**错，不是照抄模板：
 *
 * ① `vite/client` —— 解 main.ts 那三条 CSS 导入的
 *    TS2882: Cannot find module or type declarations for side-effect import of './styles/tokens.css'
 *    （本机 vue-tsc 3.3.14 + TS 6.0.3 首跑读数）。`vite/client.d.ts` 里就有
 *    `declare module '*.css' {}`，指过来即可，这是 Vite 官方做法。
 *
 * ② `declare module '*.vue'` —— 解 eslint 类型感知面在 main.ts 报的
 *    @typescript-eslint/no-unsafe-argument（`./App.vue` 在 plain TS 下解析不到 ⇒ error typed）。
 *    这条**曾经被我按记忆判成"会削弱 typecheck"而打算不写**（旧模板里那条通配声明确实有
 *    "覆盖真实 props 类型"的说法）。本批拿变异实测了三档，结论与记忆相反：
 *      A 干净树 + 无 shim   ⇒ rc=0，0 个 TS 错
 *      B 变异 + 无 shim     ⇒ App.vue(39,16) TS2322（`<Legend :title="123">` 传给 `title: string`）
 *      C 变异 + 有 shim     ⇒ **同一条 TS2322 照报**，少报 0 个
 *    机制读法：模块**解析成功**时通配 ambient 声明不参与，vue-tsc 走的是真实 SFC 解析；
 *    只有 plain `typescript`（eslint 用它，不认 `.vue`）才落到通配声明上。
 *    ⇒ 所以这一条同时成立：eslint 不再误报，vue-tsc 的抓力一分没少。
 *    实验件住在 gitignored 的本机目录（.tmp-scratch/ap-visual/e16-shim-experiment.mjs，
 *    按本仓路径书写口径：不入库的目录不带反引号），三档读数在本批取证档。
 * ==========================================================================*/
/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue';

  // 通配声明只能给通用形状：这里不带 generics，所以 props 校验由 vue-tsc 负责（见头注②）。
  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>>;
  export default component;
}
