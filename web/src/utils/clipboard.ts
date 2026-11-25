/* ============================================================================
 * clipboard.ts — 剪贴板图片提取（会话粘贴图片提问）
 *
 * 单一实现：从 ClipboardEvent.items 挑出 image/* 项转成 File。
 * 边界（P4）：非图片项（文本/HTML）一律忽略 ⇒ 纯文本粘贴不受干预；
 * 返回空数组表示"没有图片"，调用方据此决定是否 preventDefault。
 * ==========================================================================*/

/** 从剪贴板条目里提取图片 File；无图片返回空数组。
 *  DataTransferItemList 是类数组（非 Array），故用 ArrayLike 而非 readonly []。 */
export function extractImageFiles(items: ArrayLike<DataTransferItem> | undefined): File[] {
  if (!items) return []
  const files: File[] = []
  for (const item of Array.from(items)) {
    if (!item.type.startsWith('image/')) continue
    const file = item.getAsFile()
    if (file) files.push(file)
  }
  return files
}
