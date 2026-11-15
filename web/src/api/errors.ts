/* ============================================================================
 * errors.ts — 三条错误通道的**唯一**两个收敛点（工单件 §3 定案）
 * 为什么是两条函数而不是一个：通道一/二走 HTTP 响应（状态码在、体是 JSON），
 * 通道三走已开的 SSE 流（状态码早已发 200，兜不住，见 errors.py 自陈的那条限制）。
 * 两条函数各自对应一组分支点，后端若真收敛为信封制，改动面 = 这两个函数（工单件 §3 末句）。
 *
 * 最终态后端契约：HTTP 与流内错误帧统一 `{code, msg, request_id, details?}`。
 * 本文件以 `msg` 为唯一上屏文案来源；`details` 只在没有 `msg` 时兜底读取校验项，
 * 且**永远不读 `input`**（服务端 echo 的用户原文，可能含资料/PII）。
 * 旧 `detail` / `error` 键只作滚动升级期的兼容分支，不是新代码的契约。
 *
 * 流内 error 帧不含诊断信息（mask 函数的入参"只为语义显式，不参与返回值"），
 * 所以文案引导向 request_id / 服务端日志，**不做**一个"错误详情"区去承接它。
 * ==========================================================================*/

/** 通道二（未捕获异常的统一信封）与通道一（FastAPI 原生 detail）都可能的体形状。 */
type ErrorBody = Record<string, unknown>

/** 422 数组项里被本项目读到的键。**不读 `input`**（纪律 ②）。 */
interface ValidationItem {
  readonly loc?: unknown
  readonly msg?: unknown
}

function fieldOf(item: ValidationItem): string {
  // `Array.isArray` 把 `unknown` 收窄成 `any[]` —— 这里显式标回 `readonly unknown[]`，
  // 不靠 `as`：窄化后的元素类型本该是 unknown（服务端给什么我们都不假定）。
  const loc: readonly unknown[] = Array.isArray(item.loc) ? item.loc : []
  const last = loc[loc.length - 1]
  // loc 末段就是字段名（`["body","checkpoint_id"]` → checkpoint_id）。只接基元两种：
  // string 与 number（pydantic 给路径段时数组下标会是整数）。其余一律写「未给出」——
  // 上屏一句 `[object Object]` 比上屏「字段名未给出」更坏：前者假装读到了，后者是诚实。
  if (typeof last === 'string' && last !== '') return last
  if (typeof last === 'number') return String(last)
  return '（字段名未给出）'
}

function reasonOf(item: ValidationItem): string {
  return typeof item.msg === 'string' && item.msg !== '' ? item.msg : '校验失败'
}

/** 422 分支：每条只取「字段名 + 原因」，条与条之间分号连接，绝不展开整个数组。 */
function describeValidationDetail(items: readonly unknown[]): string {
  const parts: string[] = []
  for (const raw of items) {
    if (raw === null || typeof raw !== 'object') continue
    const item = raw as ValidationItem
    parts.push(`${fieldOf(item)}：${reasonOf(item)}`)
  }
  if (parts.length === 0) return '请求字段校验失败（服务端未给出可展示的字段名）'
  return `字段校验失败 —— ${parts.join('；')}`
}

/**
 * HTTP 通道（4xx / 5xx）→ 一句可直接上屏的文案。
 * 不抛异常：体不是 JSON、或 JSON 形状不认识时，返回带状态码的兜底句而不是 TypeError。
 */
export async function describeError(resp: Response): Promise<string> {
  // 不写 `= null` 初值：两个分支都会赋值，那个初值永远读不到（lint 的 no-useless-assignment
  // 报的就是它）。真正要兜的是 `resp.json()` 抛 —— 下面 catch 里赋的 null 才是有意义的哨兵。
  let body: unknown
  try {
    body = await resp.json()
  } catch {
    body = null
  }

  if (Array.isArray(body)) return describeValidationDetail(body)

  if (body !== null && typeof body === 'object') {
    const o = body as ErrorBody

    // 最终态：所有 4xx/5xx 均为 {code, msg, request_id, details?}
    if (typeof o.msg === 'string' && o.msg !== '') {
      const rid = typeof o.request_id === 'string' ? o.request_id : ''
      return rid === '' ? o.msg : `${o.msg}（request_id ${rid}，请凭它查服务端日志）`
    }

    // 兼容分支：滚动升级期旧服务仍可能返回 {detail: [...]} 或 {detail: "..."}。
    const detail = o.detail
    if (Array.isArray(detail)) return describeValidationDetail(detail)
    if (Array.isArray(o.details)) return describeValidationDetail(o.details)
    if (typeof detail === 'string' && detail !== '') {
      if (resp.status === 401 || resp.status === 403) {
        return `登录凭据无效或已过期（服务端：${detail}）`
      }
      return `${detail}（HTTP ${resp.status}）`
    }
  }

  return `服务返回 HTTP ${resp.status}，响应体不是可解析的错误信封`
}

/** 最终态流内 error 帧用 `msg`；后两键仅作滚动升级期兼容。 */
const STREAM_TEXT_KEYS = ['msg', 'error', 'message'] as const

/**
 * SSE 流内 error 帧 → 一句可直接上屏的文案。同步函数：帧已在手里，没有要 await 的东西。
 * 载荷除取到的一句文案外**一律不渲染**（工单件 §2.2 的同一条纪律，只是这里防的是错误帧）。
 */
export function describeStreamError(payload: unknown): string {
  let text = ''
  if (typeof payload === 'string') {
    text = payload
  } else if (payload !== null && typeof payload === 'object') {
    const o = payload as ErrorBody
    for (const key of STREAM_TEXT_KEYS) {
      const v = o[key]
      if (typeof v === 'string' && v !== '') {
        text = v
        break
      }
    }
  }
  // 一个键都没命中时不谎称"详情"，用服务端那句固定文案的语义占位（通道三没有诊断信息）。
  const shown = text === '' ? '服务器内部错误，请稍后重试' : text
  return `${shown}（流内帧不携带诊断细节，请凭本页的 request_id 查服务端日志）`
}
