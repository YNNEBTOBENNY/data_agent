"""统一出域 sanitizer：所有 LLM 请求在适配层出口经过此处。

职责：
1. PII 正则替换（手机号、身份证、邮箱）
2. 敏感对象黑名单过滤（列名/注释关键词，由调用方传入过滤，此处提供判定）
3. 数字常量白名单策略（V1 只做 PII + 敏感过滤，绝对数值拦截由调用方按白名单约束）
"""
import re

# 中国手机号
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
# 18 位身份证
_ID_CARD_RE = re.compile(r"(?<!\d)(\d{17}[\dXx])(?!\d)")
# 邮箱
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def replace_pii(text: str) -> str:
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _ID_CARD_RE.sub("[ID_CARD]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    return text


def is_sensitive_name(name: str, keywords: list[str]) -> bool:
    """判断表/列名或注释是否命中敏感关键词（子串匹配，忽略大小写）。"""
    lowered = name.lower()
    return any(k in lowered for k in keywords)


def sanitize(text: str, sensitive_keywords: list[str]) -> str:
    """对即将出域的一段文本做 PII 替换与敏感关键词处理。

    注意：敏感对象的过滤应尽量在「组装 prompt 之前」由调用方完成（源头过滤），
    此处仅对已进入文本的敏感关键词做兜底打码。
    """
    text = replace_pii(text)
    for kw in sensitive_keywords:
        text = re.sub(re.escape(kw), "[REDACTED]", text, flags=re.IGNORECASE)
    return text
