"""规范化序列化与 manifest。

字节一致的三个来源：
1. 记录按 instance_id 排序；
2. JSON 用 sort_keys + 紧凑分隔符 + 固定换行 LF；
3. 输出里不含时间戳、主机名、绝对路径等易变字段。
"""

from __future__ import annotations

import hashlib
import json


def canonical_bytes(obj) -> bytes:
    return json.dumps(
        obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def instance_hash(rec: dict) -> str:
    """单条实例的哈希：整条规范化 JSON（含全部字段）的 sha256。"""
    return sha256_hex(canonical_bytes(rec))


def manifest_hash(entries: list[tuple[str, str]]) -> str:
    """全量 manifest 哈希：对排序后的 `<instance_id>\\t<sha256>\\n` 求 sha256。"""
    payload = "".join(f"{iid}\t{digest}\n" for iid, digest in sorted(entries)).encode("utf-8")
    return sha256_hex(payload)


def subset_bytes(records: list[dict]) -> bytes:
    ordered = sorted(records, key=lambda rec: rec["instance_id"])
    return b"".join(canonical_bytes(rec) + b"\n" for rec in ordered)


def json_bytes(obj) -> bytes:
    return (
        json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
