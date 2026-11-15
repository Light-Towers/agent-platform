/* ============================================================================
 * health.ts — /health 字段的屏上灯阵字典（从 poc-health.html 转正为真实工程源）
 * 本文件是「屏上字典」的**唯一真相源**：门禁 check-tokens.mjs 断言 6 现读此处
 * 与后端两层 HealthResponse 字段集双向比对，后端加一个字段而这里没动 ⇒ 门禁红。
 * 形状纪律与 events.ts 的 EVENT_LEGEND 同形：一行一键、值对象同行
 * （门禁的 key 抽取按行首纯空白后的第一个标识符/引号串算，多键共一行会漏读）。
 * 四档形状的语义（true 实心 / false 空心 / null 警示 / 字符串·对象 方块）由渲染层
 * 解释，本文件只登记字段分组与判读说明，不写死数量。
 * ==========================================================================*/

export interface LampRow {
  readonly why: string
}

/** 分组 key 并集必须 == 派生 /health 字段全集（不写死分组数/字段数）。 */
export const HEALTH_LAMP_GROUPS: Record<string, string[]> = {
  '平台基座':     ['status', 'version', 'storage', 'planner', 'auth_enabled', 'identity_mode'],
  '检索与缓存':   ['llm', 'search', 'embedding_backend', 'embedding_real', 'cache_backend', 'cache_ready', 'cache_degraded_reason', 'cache_stats'],
  '执行平台':     ['admission', 'coordination', 'revert', 'scheduler', 'control_plane', 'cost_governance', 'forensic'],
  '观测':         ['otel', 'otel_status', 'langfuse_enabled', 'langfuse_ready'],
  '数据面与工具': ['sql_backend', 'nl2sql', 'mcp', 'guard_enabled', 'dependencies'],
}

/** 字段名 → 判读说明（一行一键，门禁同形读取）。 */
export const HEALTH_LAMP_WHY: Record<string, string> = {
  status: '服务整体健康状态',
  version: '服务版本',
  storage: '平台库后端',
  planner: '当前 Planner 策略',
  auth_enabled: '是否启用入站鉴权（只接受登录令牌）',
  identity_mode: '身份断言模式（不读具体值）',
  llm: 'LLM 可用',
  search: '联网搜索可用',
  embedding_backend: '实际 embedder 类型名',
  embedding_real: '语义检索真值（false = 按字面比对）',
  cache_backend: '缓存后端',
  cache_ready: '缓存就绪',
  cache_degraded_reason: '降级真因',
  cache_stats: '命中/未命中计数',
  admission: '准入限流已装配且启用',
  coordination: '会话并发协调启用',
  revert: '对话回退启用',
  scheduler: 'ExecutionScheduler 已装配',
  control_plane: 'ControlPlane 已装配',
  cost_governance: '成本治理已装配',
  forensic: '轨迹/取证存储已装配',
  otel: 'OTel 追踪开关',
  otel_status: '观测内核状态机真值',
  langfuse_enabled: 'Langfuse 已装配',
  langfuse_ready: 'Langfuse 后端可达',
  sql_backend: '问数数据面方言（由持业务库的服务上报）',
  nl2sql: '问数服务已注册',
  mcp: 'MCP 工具启用',
  guard_enabled: 'SQL 守卫启用',
  dependencies: '依赖探活明细',
}

/** 拉取 /health 真实状态（免鉴权探针路径，经 vite 代理 /health）。返回扁平字段字典，
 *  灯阵按四档形状渲染（见 HealthView.vue）。不注入凭据头——/health 在免检路径上。 */
export async function getHealth(): Promise<Record<string, unknown>> {
  const res = await fetch('/health')
  if (!res.ok) throw new Error(`/health ${res.status}`)
  return (await res.json()) as Record<string, unknown>
}
