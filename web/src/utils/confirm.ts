/* ============================================================================
 * confirm.ts — 破坏性操作的二次确认（单一实现，plan-image-vl-summary-and-delete-confirm §2.2）
 *
 * 用户视角：用户看到的必须与发生的一致——不可逆操作明确写"不可恢复"，可恢复操作
 * 明确写"可恢复"。4 处删除/下线调用本件，文案风格一致；以后要升级成"输入名称确认"
 * 只改这一处（P3：全局统一靠机制，不靠各调用点记得写对文案）。
 * ==========================================================================*/

export interface DestructiveSpec {
  /** 动作名，如「删除会话」「永久删除文档」 */
  readonly action: string
  /** 对象名，如会话标题 / 文档名 / 知识库名 */
  readonly target: string
  /** 具体后果，如"该会话及全部对话历史将被移除" */
  readonly consequence: string
  /** 是否可逆；false = 不可恢复（文案带醒目提示） */
  readonly reversible: boolean
}

/** 弹出二次确认；返回 true 才继续执行。纯函数式封装，便于行为测试注入。 */
export function confirmDestructive(
  spec: DestructiveSpec,
  confirmImpl: (message: string) => boolean = (message) => window.confirm(message),
): boolean {
  const recoverHint = spec.reversible
    ? '该操作可恢复。'
    : '⚠ 此操作不可恢复，请确认后再继续。'
  const message = `${spec.action}：${spec.target}\n${spec.consequence}\n${recoverHint}\n\n确定继续吗？`
  return confirmImpl(message)
}
