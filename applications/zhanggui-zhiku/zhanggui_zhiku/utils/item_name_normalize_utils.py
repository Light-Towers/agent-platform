# ===================== 商品名规范化 =====================
import re

# 品牌前缀黑名单：识别结果以这些词开头时剥离（保证同型号商品名跨文档/跨轮次一致）
_BRAND_PREFIXES = ("兄弟", "brother", "Brother", "BROTHER")

# 内部料号后缀模式：如 "D01WD7001-00"（字母+数字+横线尾缀），剥离避免同型号识别出多个变体
_PART_NO_RE = re.compile(r"[A-Za-z]{1,3}\d{2}[A-Za-z]{3,}\d+-\d{2,}$")


def normalize_item_name(name: str) -> str:
    """
    商品名规范化（导入侧/检索侧共用，保证精确过滤口径一致）
    规则：
        1. 去除全部空白字符（如 "HAK 180 烫金机" → "HAK180烫金机"）
        2. 剥离品牌前缀（兄弟/Brother），保留型号+品类
        3. 剥离尾部内部料号（如 D01WD7001-00），避免同型号识别出多个变体
    参数：
        name: 原始商品名（LLM 识别结果或用户查询提取结果）
    返回：
        str: 规范化后的商品名；空值原样返回
    """
    if not name:
        return name
    s = str(name)
    # 1. 去除全部空白字符
    s = re.sub(r"\s+", "", s)
    # 2. 剥离品牌前缀（仅开头匹配一次）
    for prefix in _BRAND_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix) :]
            break
    # 3. 剥离尾部内部料号
    s = _PART_NO_RE.sub("", s)
    return s
