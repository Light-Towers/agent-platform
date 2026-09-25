# DeepSeek Harness (deepseek-ai/deepseek-harness) GitHub Discussions 高质量讨论梳理

> 数据来源：`deepseek-ai/deepseek-harness` 仓库 GitHub Discussions
> 抓取方式：GraphQL `search(type:DISCUSSION)` + `--input` 批量检索（按 31 个架构/使用/排错/功能/生态关键词）+ 高互动排序（评论数×3 + 点赞×2）+ 正文/评论抓取
> 说明：该仓库 Discussions 总量极大（实测 3 万+，官方 `totalCount` 字段不可靠），本报告不追求穷尽，而是**定向筛选出对理解项目有价值的高质量讨论**，并排除加群/抽奖/纯吐槽/重复提问/无信息量内容。
> 仓库定位：**"Everything is a Plugin"（一切皆插件）**，基于 Cordis 插件内核，Bundle / Profile / Patch 三层分离的 Agent 工程化平台（185k+ stars）。

---

## 一、项目架构与设计理念（Architecture & Design）

### 🏛️ 核心架构概念（社区共识，多位深度用户提炼）
- **Bundle（能力包）= 预打包的零件套装**：打包模型接口、工具箱、沙盒、会话记录等，本质是带一份配置层的 npm 包（如 `@deepseek-ai/dsh-host`、`dsh-web`）。
- **Profile（场景配置）= 用什么零件搭什么场景**：按需编排 Bundle 组合，是"产品迭代"与"生态积累"解耦的关键。
- **Patch（补丁）= 个人微调**：在不改官方 Bundle 的前提下就地改配置/注入。
- **Everything is a Plugin / Cordis**：运行时内核是 Cordis，每块功能都是独立包；插件通过 `Service` 注入、通过 `profile` 编排。
- 官方 Announcement（[#1797](https://github.com/deepseek-ai/deepseek-harness/discussions/1797)）明确：项目仍处 early preview，官方"读每一条反馈"，分类发帖。

### 🔧 架构级深度讨论（含源码级根因）
| # | 主题 | 核心结论 / 要点 |
|---|------|----------------|
| [#2699](https://github.com/deepseek-ai/deepseek-harness/discussions/2699) | `pnpm dsh web` 启动失败：`--expose-internals is required for HMR` | 根因：web 组合包在启动收尾仍会**重挂一个 watch-only HMR**（无 module root），而该路径需要 loader 内部权限。多位用户从 `profile-boot.ts`、`cordis-plugin-hmr`、`vendor` 代码在 lint 中双层不可见等角度做了第一性原理拆解。 |
| [#1550](https://github.com/deepseek-ai/deepseek-harness/discussions/1550) | 冷启动加载大/损坏会话日志会**阻塞整个 Web 服务** | 根因：服务端在分页响应前于 Node 主线程全量解压/解析/校验事件流；一条结构性有效大会话或一条带 rollback 的会话即可让全站 TCP 连接挂起。是会话损坏家族（#1333/#1452 seq gap）的"可用性放大器"。已有离线检测（dsh-doctor S6/S7）覆盖。 |
| [#1886](https://github.com/deepseek-ai/deepseek-harness/discussions/1886) | `tokenUsage` 投影不合并 compaction/summary 用量、重试步用量被替换而非累加 | 在 4 会话/8650 事件/78 用量样本上实测发现；已有 fork 修复（按 finish reason 识别 attempt 边界、将 compaction 调用计入总计），多人 corpus 验证。 |
| [#984](https://github.com/deepseek-ai/deepseek-harness/discussions/984) | `dsh-type-meta` 未发布到 npm，阻断社区插件 `pnpm` 安装 | 该包被 `dsh-agent` 等经 peer 链传递依赖，但 npm 上 404；npm 默认 train 解析到坏版本。变通：从本地 checkout 安装插件（profile 经 harness 回退 node_modules 解析）。 |
| [#2763](https://github.com/deepseek-ai/deepseek-harness/discussions/2763) | 包族 npm `dist-tag latest` 不一致（0.0.1-rc.1 的 peer 引用已改名/不存在的包名），裸装必 ERESOLVE | 根因：多数包 latest 停在首次发布版，而 `dsh`/`dsh-tools` 已 rc.7；全注册表扫描（916 插件/324 可装）显示 **77 个插件被坏 latest 命中**。Workaround：整包族钉同一条线（如 0.1.0-rc.7）。 |
| [#3192](https://github.com/deepseek-ai/deepseek-harness/discussions/3192) | CHA2A：智能体生态身份与来源认证规范（草案） | 四层标识 × 分层签名 × 认证等级，解决"谁发布/是否被改/在哪上架/可信度几级"。**代码级核验**确认其建立在官方已有机制上（SkillSource 七桶、SKILL.md frontmatter 必填、bundle 分发单位）。与 #2269 互补。 |
| [#2269](https://github.com/deepseek-ai/deepseek-harness/discussions/2269) | 提案：市场识别层插件开发规范 STANDARD.md | 填补"框架层文档"与"插件层文档"之间的**空白层**（仓库怎么写才能被市场正确收录/安装）。核心治理点：**特征驱动扫描需"显式声明优先"**，避免根目录 install 脚本抢先判定 cordis 插件（paper-tutor 劫持根因）。 |
| [#2930](https://github.com/deepseek-ai/deepseek-harness/discussions/2930) | 致团队的产品建议：命名约定 | 高度认可 Bundle/Profile/Patch 三层分离的前瞻设计，但指出术语存在"命名过载与边界模糊"。官方回应：`tianyicui` 确认 0.1 早期版本命名未经仔细设计，正在考虑改进。 |

---

## 二、使用方式 / 安装 / 配置（Usage, Install, Configure）

### 🚀 入门与部署
- **启动方式**：`npx @deepseek-ai/dsh web`（默认监听 `127.0.0.1:3080`）。全局安装后可简化为 `dsh web`（[#576](https://github.com/deepseek-ai/deepseek-harness/discussions/576)）。
- **平台形态**：DSH 是 **Web（浏览器）端**而非桌面端（[#601](https://github.com/deepseek-ai/deepseek-harness/discussions/601)）。想做桌面端可用 Electron 套壳，或 Rust 重写（[deepseek-harness-rust](https://github.com/bobleer/deepseek-harness-rust)，[#303](https://github.com/deepseek-ai/deepseek-harness/discussions/303)）。社区持续呼吁官方出 CLI/TUI（[#67](https://github.com/deepseek-ai/deepseek-harness/discussions/67)、[#303](https://github.com/deepseek-ai/deepseek-harness/discussions/303)）。
- **Docker 部署**：社区提供开箱即用镜像（Docker Hub / GHCR 同步），内置 Node 反向代理解决"只允许回环地址"限制（[#1762](https://github.com/deepseek-ai/deepseek-harness/discussions/1762)）。⚠️ 公开 Demo 地址慎填自己的 API Key。
- **国内/代理环境**：`NODE_USE_ENV_PROXY=1 pnpm dsh web --host 127.0.0.1` 可让 Node fetch 走代理（[#175](https://github.com/deepseek-ai/deepseek-harness/discussions/175)）。

### 🔌 插件安装与管理
- **官方插件通道**：`dsh plugin --profile web add <pkg>` 后**重启生效**（[#1096](https://github.com/deepseek-ai/deepseek-harness/discussions/1096)）。
- **社区插件目录/市场**（解决"1700+ 插件怎么找"的刚需）：
  - [dshbase](https://dshbase.com)（[#1012](https://github.com/deepseek-ai/deepseek-harness/discussions/1012)）：122 个插件逐个实测（安装/激活/启动），带精确安装命令与分类筛选。
  - [mydsh.dev](https://mydsh.dev)（[#1597](https://github.com/deepseek-ai/deepseek-harness/discussions/1597)、[#2687](https://github.com/deepseek-ai/deepseek-harness/discussions/2687)）：3650+ 已核验插件，设置页内完成浏览/安装/启停/卸载，**七态生命周期管理**（未安装→已装未启→已启待重启→运行中→已停待重启→不兼容→安装失败）。
  - 自然语言插件搜索：[dsh-plugin-finder](https://github.com/ihuajiu/dsh-plugins-finder)（[#1096](https://github.com/deepseek-ai/deepseek-harness/discussions/1096)）、[dsh-plugin-search](https://github.com/zoahdev/dsh-plugin-search)（[#1715](https://github.com/deepseek-ai/deepseek-harness/discussions/1715)）。
- **第三方插件发行为何难**：[#1989](https://github.com/deepseek-ai/deepseek-harness/discussions/1989)（dsh-compass 作者复盘）— 仓库内开发时借的是大仓的目录服务/读取接口/构建/测试，拆出去发单包时这些依赖要么自带要么砍掉，解耦本身就是一天工作量。是"官方文档偏架构、缺第三方发行教程"的实证。
- **中文实战指南共建**：[#1477](https://github.com/deepseek-ai/deepseek-harness/discussions/1477)（插件实验室群，大纲含安装启动/Manifest/版本兼容/权限报错/从零写插件/安全与许可证）。

---

## 三、常见问题排查（Troubleshooting）

> 这部分是社区贡献最密集、最有信息量的区域。多人把重复故障归纳成了"故障家族"并做了源码级根因。

### 🔒 网络 / 暴露 / 403
- **`--host 0.0.0.0` 不支持（按设计）**：Web API 可驱动 agent 动作（含 bash 执行），远程认证尚未就绪，故意只放行 `127.0.0.1`；转发到 0.0.0.0 后会 workspace 加载失败/文件选择器报错（[#76](https://github.com/deepseek-ai/deepseek-harness/discussions/76)）。
- **`/api/*` 全部 403**：服务端信任围栏要求 `Host` 与 `Origin` 严格一致（loopback）。代理改写/跨站/localhost 与 127.0.0.1 混用都会 403；curl 直连 200 证明服务端正常（[#313](https://github.com/deepseek-ai/deepseek-harness/discussions/313)）。改用 `localhost:3080` 即可。
- **`crypto.randomUUID is not a function`**：内网明文 HTTP（非 localhost/非 HTTPS）属非安全上下文，前端无条件调用全局 Web Crypto 抛异常（[#1919](https://github.com/deepseek-ai/deepseek-harness/discussions/1919)）。

### 📦 安装 / 依赖 / 原生模块
- **`npx @deepseek-ai/dsh web` 无限卡死（npm 依赖解析死循环，CPU 100%）**：根因是 **peer dependency 回溯（Arborist idealTree）死循环**，非网络/cache（[#3786](https://github.com/deepseek-ai/deepseek-harness/discussions/3786)）。已实测可用的规避：换 npm 版本/固定包族版本线。官方 `tianyicui` 介入跟进。
- **ArchLinux/WSL 无法安装**：多为 `node-pty` 原生模块构建问题；可换 `bun` 安装（其白名单含 node-pty），或手动装 node-pty + base-devel（[#49](https://github.com/deepseek-ai/deepseek-harness/discussions/49)）。
- **Android/Termux 无法运行**：是**三层构建问题叠加**（sharp → node-pty → 另两个原生依赖）+ 两个运行时阻塞（sharp + HMR flag），分步可解（[#136](https://github.com/deepseek-ai/deepseek-harness/discussions/136)）。
- **Windows 目录选择器失败 `directory picker failed`**：`koffi` 模块（调用 Windows API）未编译成功；需本地有 C++ 编译器（cmake）重装，或禁用 directory-picker 插件（[#30](https://github.com/deepseek-ai/deepseek-harness/discussions/30)、[#197](https://github.com/deepseek-ai/deepseek-harness/discussions/197)）。

### 🤖 模型 / LLM 适配
- **`DeepSeek-V4-Flash` 流式模式所有工具报 `unknown tool ""`**：`translate.ts` 的 SSE 流式解析**每分块覆盖而非累加** `name`/`id`，后续空 delta 抹掉已解析的工具名（[#725](https://github.com/deepseek-ai/deepseek-harness/discussions/725)）。修复见源码 159–160 行；另注意其对 hy3/longcat 等 `null` delta 也需兼容。
- **自定义网关 developer role 不兼容（400）**：`llm-pi-ai` 未暴露 `compat.supportsDeveloperRole`，部分网关（火山/百炼/DashScope/newapi）只支持 user role（[#280](https://github.com/deepseek-ai/deepseek-harness/discussions/280)）。绕路：起 api gateway 改写 role，或用 [pi2dsh](https://github.com/weijiafu14/pi2dsh) 注册原生 LLM route。
- **本地 LLM 5 分钟超时**：是 `pi-ai` adapter 默认 `300000ms`，顶层 `settings.yaml` 配置被忽略；须把 timeout 写在**实际选中的 provider route** 上（[#3157](https://github.com/deepseek-ai/deepseek-harness/discussions/3157)）。
- **pi-ai catalog 不实时拉模型**：对 opencode-go 等走写死 catalog 快照，新模型不显示；手动声明 openai-completions 路由又会把同提供商模型拆成两个 provider（[#3816](https://github.com/deepseek-ai/deepseek-harness/discussions/3816)）。
- **`Output token limit reached`**：多为生成命中配置的输出上限，而非上下文溢出；经 Ollama 等本地模型更易触发（[#1166](https://github.com/deepseek-ai/deepseek-harness/discussions/1166)）。

### 🧰 会话 / 工具 / 运行时崩溃
- **工具执行失败后 Session 卡死（未配对 tool_call）**：tool 异常在 `prepare()` 阶段抛出，未产生对应 tool message，导致 `assistant tool_calls must be followed by tool messages` 永久卡死（[#1841](https://github.com/deepseek-ai/deepseek-harness/discussions/1841)）。属 #1697 家族（dual-instance symbol mismatch）。
- **极简模式 persistent bash 每次卡顿 3.5s+**：旧基座（rc.6 时代）存在 PS1/PROMPT 提示符失配；**当前 main（rc.7）已从另一侧修掉**，照旧补丁反而会破坏设计（[#2656](https://github.com/deepseek-ai/deepseek-harness/discussions/2656)）。提醒：复制 fork 修复前先核对 main HEAD。
- **`sandbox escalation to "workspace-write" ... not strictly wider`**：权限模式不匹配报错（[#201](https://github.com/deepseek-ai/deepseek-harness/discussions/201)），多人复现，需确认 profile 的 sandbox 配置。

### 🩺 官方"诊断三件套"（社区沉淀的排错工具，强烈推荐）
| 工具 | 定位 | 讨论 |
|------|------|------|
| **dsh-doctor** ([moonquake2004/dsh-doctor](https://github.com/moonquake2004/dsh-doctor)) | 离线诊断，19 项检查映射到 18 个社区故障（env/profile/session），**不依赖 Docker** | [#1534](https://github.com/deepseek-ai/deepseek-harness/discussions/1534) |
| **dsh-plugin-doctor** ([zoahdev/dsh-plugin-doctor](https://github.com/zoahdev/dsh-plugin-doctor)) | 发布前插件体检（manifest→build→pack→全新 profile 安装→宿主遮蔽→环境），机器可读报告 | [#1719](https://github.com/deepseek-ai/deepseek-harness/discussions/1719) |
| **dsh-diagnose** | 按症状诊断 DSH 运行时（16 个症状家族 → 机制链→知识文档→检查命令→修复建议） | [#1739](https://github.com/deepseek-ai/deepseek-harness/discussions/1739) |
| **dsh-testkit** ([iiwish/dsh-testkit](https://github.com/iiwish/dsh-testkit)) | 真实宿主插件生命周期测试（Docker 内精确版本 DSH 启动验证），发布门禁的"另一半" | [#2038](https://github.com/deepseek-ai/deepseek-harness/discussions/2038) |

> 三者分工：dsh-doctor = 离线探测；dsh-plugin-doctor = 发布前健康检查；dsh-diagnose = 运行时症状诊断。作者已交叉链接，互相补充。

---

## 四、功能规划与官方路线图讨论（Feature Planning & Roadmap）

| # | 提案 | 社区/官方态度 |
|---|------|--------------|
| [#341](https://github.com/deepseek-ai/deepseek-harness/discussions/341) | 开放 Issues 与 Pull Requests | 多数人希望开；反对意见：当前放开"会爆炸"，标记/挑选/排期成本大。官方尚未开放（PR 通道关闭中，多处提到"等 PR 通道开"）。 |
| [#520](https://github.com/deepseek-ai/deepseek-harness/discussions/520) | 推出 Plus/Pro 订阅套餐（固定月费+周额度），保留自带 API Key | 强烈呼声，认为符合"一切皆插件"愿景；建议用插件在 UI 显示账单。 |
| [#723](https://github.com/deepseek-ai/deepseek-harness/discussions/723) | 官方插件商店 | 共识：先把"可发现"与"可信/可运行"分层。最小验收模型：发现层（topic 拉公开仓库）→结构层（root config/入口/依赖/许可/scope）→兼容层（记录实测过的 DSH commit）→安全层。 |
| [#320](https://github.com/deepseek-ai/deepseek-harness/discussions/320) | Agent 预设系统提示词支持中文 i18n | 中文母语模型被强制英文推理有损耗；建议预设提示词 i18n 或官方中文预设。反方：英文推理对复杂任务未必差。官方未明确。 |
| [#349](https://github.com/deepseek-ai/deepseek-harness/discussions/349) | 消息回撤功能（Esc 撤回） | 高频需求；实现层面最自然落点是"对当前 turn 内未/刚完成消息做本地撤回+刷新"，而非服务端硬删（参照 Claude Code 语义）。 |
| [#14](https://github.com/deepseek-ai/deepseek-harness/discussions/14) | 原生 memory 能力（迁移 Codex/Claude memory） | 已有社区桥接插件（claude-bridge/codex-bridge/opencode-bridge）及原生记忆系统 `dsh-plugin-meta-memory`（单元式组织+brief/full 两版+自动注入）。 |
| [#735](https://github.com/deepseek-ai/deepseek-harness/discussions/735) | 单轮对话 token 消耗显示 | 已由社区插件 `dsh-usage` 实现（区分 Input/Cache/Output + 预估 Cost + 52 周热力图）；强调缓存命中率（实测可达 97%）使"单轮消耗"应拆成总 token 与缓存命中/未命中两项。 |
| [#3816](https://github.com/deepseek-ai/deepseek-harness/discussions/3816) | 模型列表实时拉取而非 catalog 快照 | 提报给官方，待修。 |

> **官方路线信号**（来自 maintainer `tianyicui`/`imccyu` 在讨论中的表态）：0.1 早期版本命名/UX 未经仔细设计正在改进；破坏性更新会在未来；部分 bug 已在最新版修复；团队会跟进供应链（dist-tag/peer）问题。

---

## 五、社区最佳实践与生态（Best Practices & Ecosystem）

### 📚 社区知识库（必读）
- **[dsh-handbook](https://github.com/Electricitysheep/dsh-handbook)**（DeepSeek Harness Handbook，[#1432](https://github.com/deepseek-ai/deepseek-harness/discussions/1432)）：架构地图 + 实战手册（安装/FAQ/成本测量/生态章节），被多位插件作者交叉引用，是与官方文档互补的最佳中文资料。
- **Archify for DSH**（死链占位符已移除，2026-09-25 S-4）（[#2432](https://github.com/deepseek-ai/deepseek-harness/discussions/2432)）：从真实仓库生成可验证的交互式架构图。
- **22-note deep study of dsh's architecture**（[#1547](https://github.com/deepseek-ai/deepseek-harness/discussions/1547)）：深度架构学习笔记。

### 🧩 高质量插件范式（Show & Tell）
- **dsh-vault**（[#1457](https://github.com/deepseek-ai/deepseek-harness/discussions/1457)）：加密凭据保险库（AES-256-GCM + scrypt + RFC 6238 TOTP，零外部依赖，三态访问模式/自动锁库/防暴力破解/软删除/轮换报告）——**安全敏感插件的设计范本**。
- **topology**（[#1565](https://github.com/deepseek-ai/deepseek-harness/discussions/1565)）：实时 SVG 插件依赖图 + 第三方插件发行避坑指南（3 个真实 gotcha）。
- **dsh-github-intelligence**（[#1657](https://github.com/deepseek-ai/deepseek-harness/discussions/1657)）：196+ 只读开发情报工具跨 16 生态，无需 API key。
- **dsh-researcher**（[#2651](https://github.com/deepseek-ai/deepseek-harness/discussions/2651)）：只读项目研究 Agent 预设，**四层零写契约**（写桩永拒/指引段遮蔽/sandbox read-only/approval never），fail-closed 设计典范。
- **崩溃幸存套件（6+ 插件）**（[#2564](https://github.com/deepseek-ai/deepseek-harness/discussions/2564)）：针对"40 分钟 agent 任务第 39 分钟崩了、状态全丢"的真实痛点，提供 crash-surviving jobs / session anchors / 多平台沙盒 / 持久调度。
- **dsh-rule-evolve**（[#1906](https://github.com/deepseek-ai/deepseek-harness/discussions/1906)）：验证驱动的自我进化循环（"规则只和它的检查一样好"），把真实失败日志变成条件规则，可审计。

### 🔐 安全与供应链（社区共识）
- **插件投毒风险**：生态暴涨下，社区反复呼吁官方商店 + 标准/安全规范（[#723](https://github.com/deepseek-ai/deepseek-harness/discussions/723)、[#1115](https://github.com/deepseek-ai/deepseek-harness/discussions/1115)）。
- **远程暴露前的安全建议**：在远程认证完善前，不建议绕过 `dsh web` 的非 loopback 暴露限制（[#130](https://github.com/deepseek-ai/deepseek-harness/discussions/130)）。
- **供应链健康**：`dsh-dep-audit` / `dsh-ecosystem` 扫描官方包族 + 社区头部插件的 dist-tag/peer 一致性（[#2763](https://github.com/deepseek-ai/deepseek-harness/discussions/2763)、[#984](https://github.com/deepseek-ai/deepseek-harness/discussions/984)）。
- **插件注册表契约 RFC**（[#1846](https://github.com/deepseek-ai/deepseek-harness/discussions/1846)）：Registry Contract v2（单一 JSON schema 驱动 web 商店/CLI/agent 工具）+ `dsh plugin check`（稳定退出码）+ 检查生命周期标准化，已有 CI-green 参考实现。

### 🛠️ 工作流与工程实践
- **第三方插件开发**：官方文档偏架构，缺"怎么发第三方插件"教程；topology/dsh-compass 作者均踩过"仓库内开发易、拆出单包难"的坑。
- **会话损坏治理**：seq 序号冲突（关机中断后"中断收尾"事件与真实事件撞号，[#2342](https://github.com/deepseek-ai/deepseek-harness/discussions/2342)）、RangeError 会话搜索崩溃（[#1859](https://github.com/deepseek-ai/deepseek-harness/discussions/1859)）等，均已有离线检测覆盖。
- **成本控制**：缓存命中率实测可到 ~97%，关注"本轮缓存命中/未命中 token"比只看总 token 更有意义（[#735](https://github.com/deepseek-ai/deepseek-harness/discussions/735)）。

---

## 六、被排除的内容类型（说明筛选标准）

以下类型**未纳入**上述归纳：
1. **加群/抽奖/送插件类**：如微信/QQ 群二维码、进群抽 token、1836 款插件整理等（#1718、#1728 等）——信息密度低且易过期。
2. **纯吐槽/重复提问**：如"梁神后面会打折吗"（#32）、大量"我也遇到了"无根因的单行附和。
3. **已关闭/无信息量**：仅含标题无正文、或结论为"已在新版修复"但无技术细节的。
4. **重复故障**：同一根因的多条报告仅保留最具信息量（含源码级根因/Workaround）的一条。

---

## 七、给新用户的快速上手建议（综合结论）

1. **先读 dsh-handbook**（社区中文手册），再看官方 docs 的架构章节。
2. **启动**：`npx @deepseek-ai/dsh web` → 打开 `http://localhost:3080`（注意用 localhost 而非 127.0.0.1 混用，避免 403）。
3. **装插件**：优先用 [dshbase](https://dshbase.com)/[mydsh.dev](https://mydsh.dev) 查实测过的插件，再 `dsh plugin --profile web add <pkg>` + **重启**。
4. **排错优先用诊断三件套**：`dsh-doctor`（环境/会话）、`dsh-plugin-doctor`（插件发布前）、`dsh-diagnose`（运行时症状）。
5. **供应链坑**：装社区插件前确认官方 `@deepseek-ai` 包族 dist-tag 一致，避免混装两条版本线（ERESOLVE）。
6. **安全**：远程访问务必等官方远程认证，勿绕过 loopback 限制；凭据类插件优先选 dsh-vault 这类零外部依赖 + 三态访问模式的设计。
