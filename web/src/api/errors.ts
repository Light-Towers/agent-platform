/* ============================================================================
 * errors.ts — 三条错误通道的**唯一**两个收敛点（工单件 §3 定案）
 * 为什么是两条函数而不是一个：通道一/二走 HTTP 响应（状态码在、体是 JSON），
 * 通道三走已开的 SSE 流（状态码早已发 200，兜不住，见 errors.py 自陈的那条限制）。
 * 两条函数各自对应一组分支点，后端若真收敛为信封制，改动面 = 这两个函数（工单件 §3 末句）。
 *
 * 三条不能省的纪律，都来自实跑而不是推断：
 *   ① 422 的 `detail` 是**数组**，业务类 4xx 的是**字符串**（同一键两种形状）。
 *   ② 422 数组每项带 `input` —— 那是服务端 echo回来的用户原文，可能含资料/PII，
 *      **一律不上屏**（本文件里没有任何一处读 `input`，这不是遗漏）。
 *   ③ 流内 error 帧不含诊断信息（mask 函数的入参"只为语义显式，不参与返回值"），
 *      所以文案引导向 request_id / 服务端日志，**不做**一个"错误详情"区去承接它。
 *
 * 未覆盖的形状（exhibition-agent 的 dict detail、nl2sql 的自定义 dict）**不在此加特例**：
 * 工单件 §3 末段定的是"本批不连那两个服务，要连时按先方案后编码另开第 4/5 分支"。
 * 落到这里的行为 = 走到兜底句，不会崩、也不会假装读懂了它。
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

    // 通道二：install_error_handlers 的 500 脱敏信封 {code, msg, request_id}
    if (typeof o.msg === 'string') {
      const rid = typeof o.request_id === 'string' ? o.request_id : ''
      return rid === '' ? o.msg : `${o.msg}（request_id ${rid}，请凭它查服务端日志）`
    }

    const detail = o.detail
    if (Array.isArray(detail)) return describeValidationDetail(detail)
    if (typeof detail === 'string' && detail !== '') {
      // 鉴权失败走 FastAPI 原生 detail，文案要能把"密钥问题"和"其它 4xx"分开（A4/A8 判据）。
      if (resp.status === 401 || resp.status === 403) {
        return `密钥未填或不正确（服务端：${detail}）`
      }
      return `${detail}（HTTP ${resp.status}）`
    }
  }

  return `服务返回 HTTP ${resp.status}，响应体不是可解析的错误信封`
}

/** 流内 error 帧的载荷键在两路实现里不同名，按优先级兼容取键（工单件 §3 的一致性陷阱那条）。 */
const STREAM_TEXT_KEYS = ['error', 'msg', 'message'] as const

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
