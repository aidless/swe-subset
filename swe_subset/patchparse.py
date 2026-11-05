"""补丁文本解析：只依赖标准库，只做规则判断所需的四件事。

- 按 `diff --git` 切块
- 取被触碰的路径（b/ 侧）
- 取测试补丁的新增行文本（标题定位用）
- 识别二进制块（`Binary files ... differ` / `GIT binary patch`）
"""

from __future__ import annotations

import posixpath
import re

DIFF_PREFIX = "diff --git "
ADDED_LINE_RE = re.compile(r"^\+(?!\+\+)")
BINARY_FILES_RE = re.compile(r"^Binary files (.*) and (.*) differ$", re.MULTILINE)
PATH_TOKEN_RE = re.compile(r"^\S+/\S+\.\w+$|^\S+\.\w+$")


def split_diffs(text: str) -> list[str]:
    """把补丁切成以 `diff --git` 开头的块；没有块时返回空列表。"""
    if not text or not text.strip():
        return []
    parts = re.split(r"(?m)^diff --git ", text)
    return [DIFF_PREFIX + part for part in parts[1:]]


def _unquote_git_path(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value


def _paths_in_block(block: str) -> set[str]:
    paths: set[str] = set()
    for line in block.splitlines():
        if not line.startswith(DIFF_PREFIX):
            continue
        rest = line[len(DIFF_PREFIX) :]
        if not rest.startswith("a/"):
            continue
        rest = rest[2:]
        idx = rest.find(" b/")
        if idx < 0:
            continue
        old = rest[:idx]
        new = rest[idx + 3 :]
        # 删除文件的 b 侧是 /dev/null，仍保留 a 侧路径便于审计
        if new != "/dev/null":
            paths.add(_unquote_git_path(new))
        else:
            paths.add(_unquote_git_path(old))
    return paths


def changed_paths(text: str) -> set[str]:
    """返回补丁触碰的全部路径（b/ 侧；纯删除取 a/ 侧）。"""
    paths: set[str] = set()
    for block in split_diffs(text):
        paths |= _paths_in_block(block)
    return paths


def _binary_paths_in_block(block: str) -> set[str]:
    hits: set[str] = set()
    for match in BINARY_FILES_RE.finditer(block):
        target = match.group(2).strip()
        if target.startswith("b/"):
            target = target[2:]
        if target != "/dev/null":
            hits.add(target)
    if "GIT binary patch" in block:
        hits |= _paths_in_block(block)
    return hits


def binary_paths(text: str) -> set[str]:
    """返回补丁中无法仅凭 JSONL 还原的二进制文件路径。

    判据：该块含 `Binary files ... differ` 或 `GIT binary patch`。
    这类 diff 没有完整二进制内容。本模块不调用 git apply。
    """
    hits: set[str] = set()
    for block in split_diffs(text):
        hits |= _binary_paths_in_block(block)
    return hits


def added_text(text: str) -> str:
    """把所有新增行拼成一段规范化空白后的文本（不含 `+++` 头）。"""
    lines: list[str] = []
    for block in split_diffs(text):
        for line in block.splitlines():
            if ADDED_LINE_RE.match(line):
                lines.append(line[1:])
    return normalize_ws("\n".join(lines))


_HEADER_PREFIXES = (
    "diff --git ",
    "index ",
    "new file mode ",
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "similarity index ",
    "rename ",
    "Binary files ",
    "GIT binary patch",
    "--- ",
    "+++ ",
    "@@",
)

def content_text(text: str) -> str:
    """补丁应用后可见的文本：新增行 + 上下文行（排除删除行与 diff 头）。

    用途：定位"已存在但被本次补丁改写的测试"——这类测试的 `it(...)` 行
    往往在上下文行里，而不是新增行里（例如 wp-calypso-25257）。
    """
    lines: list[str] = []
    for block in split_diffs(text):
        for line in block.splitlines():
            if line.startswith(_HEADER_PREFIXES):
                continue
            if line.startswith("+"):
                lines.append(line[1:])
            elif line.startswith(" "):
                lines.append(line[1:])
    return normalize_ws("\n".join(lines))


def normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_path(value: str) -> str:
    normalized = posixpath.normpath(value.strip().replace("\\", "/"))
    return "" if normalized == "." else normalized
