"""输入读取与结构校验。

这里只做"能否安全处理"的硬校验（字段缺失、类型错误、重复 id、坏 JSON），
不做准入判断；准入判断全部交给 rules.py，便于审计时区分
"输入坏了"（直接失败）与"实例不合格"（记入排除清单）。
"""

from __future__ import annotations

import gzip
import json
import os
from typing import Any


REQUIRED_STR_FIELDS = ("instance_id", "repo", "base_commit", "patch", "test_patch")
REQUIRED_LIST_FIELDS = ("FAIL_TO_PASS", "PASS_TO_PASS")

# 可选字段的允许类型；None 允许（parquet 里常见 null）
OPTIONAL_TYPES: dict[str, tuple[type, ...]] = {
    "problem_statement": (str, type(None)),
    "hints_text": (str, type(None)),
    "created_at": (str, type(None)),
    "version": (str, type(None)),
    "image_assets": (dict, list, type(None)),
}


class InputError(Exception):
    """输入不可处理。消息里带行号，便于定位坏行。"""


def _is_gzip(path: str) -> bool:
    return path.endswith(".gz")


def open_input(path: str):
    if _is_gzip(path):
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return open(path, "r", encoding="utf-8", newline="")


def _type_error(field: str, expected: str, got: Any) -> str:
    return f"字段 {field!r} 应为 {expected}，实际为 {type(got).__name__}"


def validate_record(rec: Any, lineno: int) -> None:
    where = f"第 {lineno} 行"
    if not isinstance(rec, dict):
        raise InputError(f"{where}：每行必须是一个 JSON 对象，实际为 {type(rec).__name__}")

    for field in REQUIRED_STR_FIELDS:
        if field not in rec:
            raise InputError(f"{where}：缺少必需字段 {field!r}")
        if not isinstance(rec[field], str):
            raise InputError(f"{where}：{_type_error(field, '字符串', rec[field])}")
        if field != "patch" and field != "test_patch" and not rec[field].strip():
            raise InputError(f"{where}：字段 {field!r} 不能为空字符串")

    for field in REQUIRED_LIST_FIELDS:
        if field not in rec:
            raise InputError(f"{where}：缺少必需字段 {field!r}")
        value = rec[field]
        if not isinstance(value, list):
            # 常见坏输入：数据源把 JSON 数组二次编码成字符串
            if isinstance(value, str):
                raise InputError(
                    f"{where}：{_type_error(field, '字符串列表', value)}"
                    f"（该字段被编码成了 JSON 字符串，需先 json.loads）"
                )
            raise InputError(f"{where}：{_type_error(field, '字符串列表', value)}")
        for idx, item in enumerate(value):
            if not isinstance(item, str):
                raise InputError(
                    f"{where}：{field}[{idx}] 应为字符串，实际为 {type(item).__name__}"
                )

    for field, expected in OPTIONAL_TYPES.items():
        if field in rec and not isinstance(rec[field], expected):
            names = "/".join(t.__name__ for t in expected)
            raise InputError(f"{where}：字段 {field!r} 类型应为 {names}，实际为 {type(rec[field]).__name__}")


def load_instances(path: str) -> list[dict]:
    """读取 JSONL（支持 .gz），逐行校验，返回原始记录列表（不修改内容）。"""
    if not os.path.isfile(path):
        raise InputError(f"输入文件不存在：{path}")

    records: list[dict] = []
    seen: dict[str, int] = {}
    with open_input(path) as fh:
        lineno = 0
        try:
            for lineno, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise InputError(
                        f"第 {lineno} 行：JSON 解析失败（{exc.msg}，列 {exc.colno}）；"
                        f"输入被截断或不是合法 JSONL"
                    ) from exc
                validate_record(rec, lineno)
                iid = rec["instance_id"]
                if iid in seen:
                    raise InputError(
                        f"第 {lineno} 行：instance_id {iid!r} 与第 {seen[iid]} 行重复"
                    )
                seen[iid] = lineno
                records.append(rec)
        except UnicodeDecodeError as exc:
            raise InputError(f"第 {lineno} 行：输入不是 UTF-8 文本（{exc}）") from exc

    if not records:
        raise InputError("输入文件没有任何实例（空文件或全是空行）")
    return records
