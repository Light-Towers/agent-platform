# -*- coding: utf-8 -*-
"""
入站路径安全护栏纯逻辑（框架无关内核，仅依赖 stdlib）。

**全仓唯一的**「用户可控路径 → 安全落盘/读取路径」实现。背景：CodeQL
``py/path-injection`` 的 8 条 high 全部落在 ``applications/agent_federation/api/server.py``
的 4 个文件端点——各端点原先**各自**手写 ``resolve()`` + ``is_relative_to()`` containment
与 ``Path(name).name`` + 正则文件名净化。防护本身有效，但实现散落导致两个问题：

1. 语义不一致（校验面覆盖不全、异常 ``str(e)`` 直接回显给客户端）；
2. 散在 4 处的私有写法，无论 CodeQL 还是人工 review 都难以认定为统一 sanitizer。

因此本模块把它们收敛为单一实现，站点只做调用；containment 判定由
``scripts/lint_architecture.py`` P7 不变量强制（白名单外禁手写 ``is_relative_to``，
api 层文件 I/O 必须经本模块 helper）。

三个入口语义不同，勿混用：

- ``safe_join``：**拼接**语义。片段必须为相对路径，出现 ``..`` / 绝对路径 / NUL / 空即拒绝。
  适用于由服务端自己组装的目录名与文件名（如上传落盘）。
- ``resolve_within``：**解析**语义。接受调用方原样回传的整串路径，绝对与相对均可，
  但规范化后必须仍位于基准目录内。适用于对外契约里 ``?path=`` 这种
  "把此前 ``/api/files`` 列出的路径传回来"的端点（改契约会破坏既有前端）。
- ``safe_filename``：文件名净化（取 basename + 字符白名单），消除路径分隔符与 ``.``/``..``。

设计取舍：containment 按**先词法、后解析**两步走——先用 ``os.path.normpath`` 折叠 ``.``/``..``
（不访问文件系统），再用带分隔符边界的前缀判定拒掉明显越界，**之后**才 ``resolve()`` 并
复检一次（挡住 base 内指向外部的符号链接）。因此越界输入不会触发文件系统遍历，
且校验与最终使用的始终是同一个字符串。
异常消息**不含**用户输入原文，避免被 ``detail=str(e)`` 之类写法带进出站响应。
服务端留痕同样**不落路径文本**（无论入参还是解析结果）：用户回传的路径常含凭证派生的
会话目录名（``session_user-<HMAC(api_key)>``），属于 ``py/clear-text-logging-sensitive-data``
的官方处置口径「敏感数据不应写日志」；日志只留原因与**不携带原文内容的数值型结构摘要**，
需要看完整入参时从接入层访问日志取，或用同一入参本地复跑。

**跨平台语义（必读）**：入参可能来自任意客户端 OS，而 ``pathlib`` 只认**当前宿主**
的分隔符——Linux 服务端收到 Windows 客户端的 ``C:\\x\\y`` 或 ``..\\..\\win.ini`` 时，
反斜杠在 POSIX 下只是普通字符，若按宿主语义判定就会把它当成合法相对片段。
本模块因此对绝对形式与目录分隔**同时覆盖 ``/`` 与 ``\\``**，不依赖服务部署在哪个
平台（CI 的 Linux runner 实测拦住过这一类差异，见 Batch 3 的跨平台补修）。
"""

import os
import re
from pathlib import Path

from agent_core.logging import get_logger

logger = get_logger(__name__)

# Windows 语义下的显式上跳片段：safe_join 一律拒绝（比"解析后仍在 base 内"更严，可预测）
_TRAVERSAL_PART = ".."

# 文件名字符白名单：仅允许 \w（含中文）、点、连字符、空格；其余（含 / \ : * ? " < > |）替换为 _
_UNSAFE_FILENAME_RE = re.compile(r"[^\w.\- ]")

# 两套分隔符（不随宿主变）：入参可能来自 Windows 客户端，POSIX 下反斜杠同样承载分隔语义
_ANY_SEP_RE = re.compile(r"[\\/]+")

# 跨平台绝对形式：POSIX 根 `/`、Windows 盘符 `C:\` 或 `C:/`、UNC `\\server\share`
_ABS_FORM_RE = re.compile(r"^(?:[A-Za-z]:)?[\\/]")

# Windows 专属绝对形式：盘符 `C:\` / `C:/` 与 UNC `\\server\share`
_WINDOWS_ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def _split_fragments(raw: str) -> list[str]:
    """按**两套**分隔符切分并丢弃空片段与 ``.``，结果不随宿主变。"""
    return [part for part in _ANY_SEP_RE.split(raw) if part and part != "."]


def _is_foreign_absolute(raw: str) -> bool:
    """在**非 Windows 宿主**上长得像 Windows 绝对路径（或 UNC）的入参。

    这类形式不可能由本仓端点产出（POSIX 部署下 ``/api/files`` 返回的是 ``/`` 开头的
    路径），却可能被 Windows 客户端原样递过来。而 POSIX 的 ``Path`` 不认反斜杠，
    若仍按宿主语义把它当合法相对片段，就会拼出一个名字里带反斜杠的“安全”路径——
    不越界但语义难测，所以直接拒绝。

    Windows 宿主返回 ``False``：此时 ``C:\\...`` 是本平台**合法**绝对形态，必须允许
    消费者把 ``/api/files`` 返回的绝对路径原样回传（对外契约）；而 ``/etc/passwd``
    在 Windows 下规范化后不以 ``root_str`` 为前缀，由 ② 的前缀判定直接拒掉。
    """
    return os.name != "nt" and bool(_WINDOWS_ABS_RE.match(raw))


class PathTraversalError(ValueError):
    """用户可控路径越出基准目录，或含非法成分（绝对片段 / ``..`` / NUL / 空）。

    继承 ``ValueError``：宿主即使尚未适配本类型，也仍会被既有的 ``except ValueError``
    / 通用异常处理捕获，不会因新类型而漏网。
    """


def _input_shape(raw: object) -> str:
    """输入的**结构摘要**：长度 / 片段数 / 是否绝对形式，不含任何路径文本。

    数值型投影不携带原文内容，因此不会把凭证派生的会话标识（或其他敏感片段）
    写进日志，但足以区分「同一个拒绝原因下有多少种、多大的入参」。
    """
    s = str(raw)
    return f"len={len(s)} fragments={len(_split_fragments(s))} absolute={bool(_ABS_FORM_RE.match(s))}"


def _reject(raw: object, reason: str) -> None:
    """统一拒绝出口：服务端只留「原因 + 结构摘要」，异常消息与日志都不回带路径原文。

    基准目录（``root``）与入参原文**均不进日志**：前者由部署配置 / 环境变量派生，
    后者常含凭证派生的会话目录名，两者都会被 CodeQL 判为 secret
    （``py/clear-text-logging-sensitive-data``，官方处置口径为「敏感数据不应写日志」）。
    """
    logger.warning("[guardrails.fs] 拒绝路径输入 reason=%s input=%s", reason, _input_shape(raw))
    raise PathTraversalError(reason)


def _ensure_within(root: Path, candidate: Path, *, hint: object) -> Path:
    """规范化结果必须仍位于 root 内（root 自身算合法）。

    越界线索同样只记结构摘要（``hint`` 为调用方原样给入的路径）：``root``、
    解析后的绝对路径、以及入参原文都带出敏感信息，理由见 ``_reject``。
    """
    if candidate != root and not candidate.is_relative_to(root):
        logger.warning("[guardrails.fs] 拒绝越界路径 input=%s", _input_shape(hint))
        raise PathTraversalError("路径越出基准目录")
    return candidate


def safe_join(base: str | Path, *parts: str | Path) -> Path:
    """
    把（可能用户可控的）**相对**片段逐个拼到 base 下，返回解析后的绝对路径。

    任一片段为绝对路径、含 ``..``、含 NUL 或为空即抛 ``PathTraversalError``；
    拼接结果解析后若落在 base 之外（符号链接逃逸）同样抛错。

    :param base: 服务端提供的基准目录（会被 ``resolve()`` 规范化）
    :param parts: 待拼接的路径片段，逐个校验
    :return: base 之下、已规范化的绝对路径
    """
    root = Path(base).resolve()
    current = root
    for part in parts:
        raw = str(part)
        if not raw:
            _reject(part, "路径片段不得为空")
        if "\x00" in raw:
            _reject(part, "路径片段含 NUL 字节")
        p = Path(raw)
        # 绝对判定不依赖宿主：``Path.is_absolute()`` 在 POSIX 下不认盘符与反斜杠形式
        if _ABS_FORM_RE.match(raw) or p.is_absolute():
            _reject(part, "路径片段不得为绝对路径")
        if _TRAVERSAL_PART in _split_fragments(raw):
            _reject(part, "路径片段不得含 ..")
        current = current / p
    return _ensure_within(root, current.resolve(), hint=parts)


def resolve_within(base: str | Path, user_path: str | Path) -> Path:
    """
    解析调用方原样回传的路径，要求结果位于 base 内，否则抛 ``PathTraversalError``。

    与 ``safe_join`` 的区别只在入口宽容度：这里**允许绝对路径**（因为既有对外契约把
    ``/api/files`` 返回的绝对路径原样传回，收紧为"仅相对"会破坏消费者），
    但绝对路径也必须本就落在 base 内。校验顺序为三步，缺一不可：
    **① 纯词法规范化（``os.path.normpath``）→ ② 带分隔符边界的前缀判定 → ③ 才 ``resolve()``
    并复检**（挡符号链接逃逸）。② 必须先于 ③：未验证的入参不得触发文件系统访问。
    异平台的绝对形式（POSIX 宿主收到 ``C:\\...`` / UNC）一律拒绝，见
    ``_is_foreign_absolute``。

    :param base: 服务端提供的基准目录
    :param user_path: 外部输入的路径字符串（相对或绝对）
    :return: base 之下、已规范化的绝对路径
    """
    raw = str(user_path)
    root = Path(base).resolve()
    root_str = str(root)
    if not raw.strip():
        _reject(user_path, "路径参数不得为空")
    if "\x00" in raw:
        _reject(user_path, "路径参数含 NUL 字节")
    if _is_foreign_absolute(raw):
        _reject(user_path, "路径含非本平台绝对路径形式")
    # ① 纯词法规范化：``os.path.normpath`` 不访问文件系统，先把 ``.`` / ``..`` 折叠定形；
    #    ``os.path.join`` 对绝对入参直接取该入参，因此相对/绝对入口都被统一成绝对形式。
    norm = os.path.normpath(os.path.join(root_str, raw))
    # ② 前缀守卫：必须先规范化再判前缀（顺序反了判定无效）。
    #    第二个合取项补**分隔符边界**：否则 ``/data/root`` 基准会把兄弟目录 ``/data/root_evil``
    #    也判为在内（naive ``startswith`` 的真实漏洞）；两侧都补边界后，base 自身仍算合法。
    if norm.startswith(root_str) and (norm == root_str or norm.startswith(root_str + os.sep)):
        try:
            # ③ 通过 ①② 之后**才**允许接触文件系统：``resolve()`` 用于展开符号链接，
            #    交由下方的 ``_ensure_within`` 复检；base 内的软链指向外部时在那一步被拒。
            resolved = Path(norm).resolve()
        except OSError:
            # 某些平台对非法字符/超长路径在 resolve 阶段即报错，不外泄细节
            _reject(user_path, "路径无法解析")
    else:
        _reject(user_path, "路径越出基准目录")
    result = _ensure_within(root, resolved, hint=user_path)
    if os.name != "nt" and "\\" in raw:
        # POSIX 宿主下反斜杠不是分隔符，`..\\evil` 会被 Path 当成单个合法片段从而绕过穿越
        # 检查。故再按“反斜杠也是分隔符”解释一遍，两种解释任一越界即拒。这一步**纯词法**
        # （不再第二次触碰文件系统）：主解释已经在 ③ 做过解析后复检，这里的职责只是挡住
        # 宿主语义误读。
        alt = Path(os.path.normpath(os.path.join(root_str, *_split_fragments(raw))))
        if alt != root and not alt.is_relative_to(root):
            _reject(user_path, "路径越出基准目录")
    return result


def safe_filename(name: str | None) -> str:
    """
    上传/落盘文件名净化：取 basename，字符白名单过滤，``.``/``..``/空归一为 ``_``。

    只负责"变成单个安全片段"，是否拼到哪个目录由调用方经 ``safe_join`` 决定。
    basename 按**两套**分隔符取（``Path().name`` 在 POSIX 下不去反斜杠目录）。
    """
    base = _split_fragments((name or "").rstrip("/\\"))
    safe = _UNSAFE_FILENAME_RE.sub("_", base[-1] if base else "")
    if safe in (".", "..", ""):
        return "_"
    return safe
