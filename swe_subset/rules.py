"""准入规则：每条规则一个 id、一段可复核的理由、一个纯函数判据。

规则只读取实例自身字段，不依赖外部仓库、不联网、不执行代码。
规则顺序固定：先记录"第一个失败规则"（waterfall），同时记录"独立失败集合"。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

from .patchparse import (
    binary_paths,
    changed_paths,
    content_text,
    normalize_path,
    normalize_ws,
    split_diffs,
)

# 视为"非代码资产"的扩展名：有它们不影响语言判定
ASSET_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".tif", ".tiff",
    ".md", ".txt", ".rst", ".json", ".yml", ".yaml", ".toml", ".lock", ".cfg", ".ini",
    ".csv", ".html", ".css", ".scss", ".less", ".map", ".snap", ".golden",
}

LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
    ".vue": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".scala": "scala",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c-family",
    ".h": "c-family",
    ".cc": "c-family",
    ".cpp": "c-family",
    ".cxx": "c-family",
    ".hpp": "c-family",
    ".cs": "csharp",
    ".swift": "swift",
    ".m": "objective-c",
    ".mm": "objective-c",
    ".ex": "elixir",
    ".exs": "elixir",
    ".erl": "erlang",
    ".hs": "haskell",
    ".clj": "clojure",
    ".lua": "lua",
    ".pl": "perl",
    ".pm": "perl",
    ".r": "r",
    ".jl": "julia",
    ".sh": "shell",
    ".bash": "shell",
}


@dataclass(frozen=True)
class RuleResult:
    ok: bool
    detail: str


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    rationale: str
    evaluate: Callable[[dict], RuleResult]


def _list_of_names(value) -> list[str]:
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _changed_paths_both(rec: dict) -> set[str]:
    return changed_paths(rec["patch"]) | changed_paths(rec["test_patch"])


# --------------------------------------------------------------------------
# R1: PASS_TO_PASS 必须非空
# --------------------------------------------------------------------------
def rule_p2p_nonempty(rec: dict) -> RuleResult:
    names = _list_of_names(rec["PASS_TO_PASS"])
    if not names:
        return RuleResult(False, "PASS_TO_PASS 为空，没有任何回归信号")
    return RuleResult(True, f"PASS_TO_PASS 有 {len(names)} 条")


# --------------------------------------------------------------------------
# R2: FAIL_TO_PASS 必须非空
# --------------------------------------------------------------------------
def rule_f2p_nonempty(rec: dict) -> RuleResult:
    names = _list_of_names(rec["FAIL_TO_PASS"])
    if not names:
        return RuleResult(False, "FAIL_TO_PASS 为空，没有目标断言")
    return RuleResult(True, f"FAIL_TO_PASS 有 {len(names)} 条")


# --------------------------------------------------------------------------
# R3: 每条 FAIL_TO_PASS 都能在 test_patch 中定位
# --------------------------------------------------------------------------
def locate_test(name: str, test_patch: str) -> tuple[bool, str]:
    """在 test_patch 里定位一个测试标识。

    支持三种 SWE-bench 真实存在的写法（全部是字符串/路径匹配，不执行测试）：

    1. nodeid：`tests/test_x.py::test_name` / `...::Class::method`；
       要求文件出现在被改路径里，且末段测试名出现在 post-image 文本中。
    2. fixture 路径：名字以带扩展名的路径结尾（如 `.../minBarLength/vertical-pos.js`）；
       要求该路径本身出现在 test_patch 的被改路径里。
    3. 自由标题：`describe 标题 - it 标题`；最后一段 it 标题（≥3 token）精确命中，
       或整名/至少 4 个 token 的连续后缀出现在 post-image 文本（新增行 + 上下文行）中；
       少于 4 token 且无分隔符的标题必须整名匹配，避免过宽的假阳性。

    Karma 的 fixture 测试名会带 `/base/` 前缀（浏览器里的根路径），
    定位时先剥掉该前缀再与被改路径比较。
    """
    name = normalize_ws(name)
    if not name:
        return False, "空的测试标识"

    if not split_diffs(test_patch):
        return False, "test_patch 为空或没有 diff --git 块"

    paths = {normalize_path(path) for path in changed_paths(test_patch)}
    content = content_text(test_patch)

    if "::" in name:
        file_part, _, test_part = name.partition("::")
        file_part = normalize_path(file_part)
        test_base = test_part.split("[")[0].split("::")[-1].strip()
        if file_part not in paths:
            return False, f"测试文件 {file_part!r} 不在 test_patch 被改路径中"
        if test_base and test_base in content:
            return True, f"nodeid 命中：{test_base}"
        return False, f"测试名 {test_base!r} 未出现在 test_patch 内容中"

    tokens = name.split()
    last = tokens[-1]
    # fixture 路径式标识：既可能带 suite 前缀（`Suite /base/x.js`），
    # 也可能整名就是一个路径（react-pdf 的 `packages/.../expand.test.js`）。
    candidates = [name] if last == name else [last]
    for candidate in candidates:
        if candidate.startswith("/base/"):
            candidate = candidate[len("/base/") :]
        if "/" in candidate and normalize_path(candidate) in paths:
            return True, f"fixture 路径命中：{candidate}"

    if name in content:
        return True, "完整标题命中"

    # wp-calypso 风格：`suite - it 标题`。分隔符不是标题的一部分，
    # 所以先按最后一个分隔符取出 it 标题，允许 3-token 的短标题精确命中。
    if " - " in name:
        it_part = normalize_ws(name.rsplit(" - ", 1)[1])
        if it_part in content and len(it_part.split()) >= 3:
            return True, f"it 标题命中：{it_part}"

    # 其余标题按"后 N 个 token 连续命中"处理；过滤掉独立分隔符 token。
    title_tokens = [token for token in tokens if token not in {"-", "–", "—"}]
    for size in range(len(title_tokens) - 1, 3, -1):
        candidate = " ".join(title_tokens[-size:])
        if candidate in content:
            return True, f"标题后 {size} 个 token 命中：{candidate}"

    return False, "测试标识未出现在 test_patch 的 post-image 文本中"


def rule_f2p_locatable(rec: dict) -> RuleResult:
    names = _list_of_names(rec["FAIL_TO_PASS"])
    if not names:
        return RuleResult(False, "FAIL_TO_PASS 为空，无法定位")
    missing: list[str] = []
    for name in names:
        ok, _ = locate_test(name, rec["test_patch"])
        if not ok:
            missing.append(name)
    if missing:
        preview = "；".join(missing[:3])
        more = "" if len(missing) <= 3 else f" 等 {len(missing)} 条"
        return RuleResult(False, f"{len(missing)}/{len(names)} 条无法定位：{preview}{more}")
    return RuleResult(True, f"{len(names)}/{len(names)} 条均可定位")


# --------------------------------------------------------------------------
# R4: patch 与 test_patch 合起来只涉及一种语言
# --------------------------------------------------------------------------
def rule_single_language(rec: dict) -> RuleResult:
    paths = sorted(_changed_paths_both(rec))
    if not paths:
        return RuleResult(False, "两个补丁都没有可解析的被改文件")

    languages: set[str] = set()
    unknown: list[str] = []
    assets = 0
    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        if ext in ASSET_EXTENSIONS:
            assets += 1
            continue
        language = LANGUAGE_BY_EXTENSION.get(ext)
        if language is None:
            unknown.append(path)
            continue
        languages.add(language)

    if unknown:
        preview = "、".join(unknown[:3])
        more = "" if len(unknown) <= 3 else f" 等 {len(unknown)} 个"
        return RuleResult(False, f"存在无法归类语言的被改文件：{preview}{more}")
    if not languages:
        return RuleResult(False, f"被改文件只有非代码资产（{assets} 个），没有可判定语言")
    if len(languages) > 1:
        return RuleResult(False, f"跨语言：{', '.join(sorted(languages))}")
    return RuleResult(True, f"单一语言：{next(iter(languages))}（{len(paths)} 个文件，含 {assets} 个资产）")


# --------------------------------------------------------------------------
# R5: 路径必须是仓库内相对路径，且两个补丁都要有内容
# --------------------------------------------------------------------------
def rule_repo_local_paths(rec: dict) -> RuleResult:
    if not rec["patch"].strip():
        return RuleResult(False, "patch 为空")
    if not rec["test_patch"].strip():
        return RuleResult(False, "test_patch 为空")

    if not split_diffs(rec["patch"]) or not split_diffs(rec["test_patch"]):
        return RuleResult(False, "补丁没有 diff --git 头，无法解析路径")

    paths = sorted(_changed_paths_both(rec))
    if not paths:
        return RuleResult(False, "补丁没有可解析的被改文件")

    bad: list[str] = []
    for path in paths:
        raw = path.strip()
        if raw.startswith("/") or raw.startswith("\\"):
            bad.append(f"绝对路径 {path!r}")
        elif any(segment == ".." for segment in raw.replace("\\", "/").split("/")):
            bad.append(f"越界路径 {path!r}")
        elif "\x00" in raw:
            bad.append(f"路径含 NUL：{path!r}")
    if bad:
        return RuleResult(False, "；".join(bad[:3]))
    return RuleResult(True, f"{len(paths)} 个路径全部为仓库内相对路径")


# --------------------------------------------------------------------------
# R6: 不允许二进制 diff 块（今天的 fixture .png 盲区）
# --------------------------------------------------------------------------
def rule_no_binary_diff(rec: dict) -> RuleResult:
    hits = sorted(binary_paths(rec["patch"]) | binary_paths(rec["test_patch"]))
    if hits:
        preview = "、".join(hits[:3])
        more = "" if len(hits) <= 3 else f" 等 {len(hits)} 个"
        return RuleResult(
            False,
            f"含 {len(hits)} 个二进制 diff 文件（{preview}{more}）；"
            f"此类 diff 无完整二进制内容，git apply 会拒绝物化",
        )
    return RuleResult(True, "没有二进制 diff 块")


RULES: tuple[Rule, ...] = (
    Rule(
        "R1", "PASS_TO_PASS 非空",
        "PASS_TO_PASS 为空时回归信号不存在：官方 FAIL_ONLY 评分下，"
        "非目标测试失败不会进入判定（今天 dev 数据里 44/102 因此失去回归约束）。",
        rule_p2p_nonempty,
    ),
    Rule(
        "R2", "FAIL_TO_PASS 非空",
        "FAIL_TO_PASS 为空时没有目标断言，任何评分都无法区分补丁行为。",
        rule_f2p_nonempty,
    ),
    Rule(
        "R3", "FAIL_TO_PASS 可在 test_patch 中定位",
        "真实 SWE-bench 中 F2P 与 test_patch 不对应（标题拼写差异、fixture 路径写法、"
        "测试未落盘）会让评分指向不存在的测试，属于不可复核的目标。",
        rule_f2p_locatable,
    ),
    Rule(
        "R4", "补丁只涉及单一语言",
        "patch 与 test_patch 合起来若跨语言，测试执行需要多套工具链与依赖，"
        "在统一镜像/统一命令下不可复现，无法给出可比的通过/失败信号。",
        rule_single_language,
    ),
    Rule(
        "R5", "被改路径全部是仓库内相对路径",
        "绝对路径、`..` 越界或空补丁会让补丁无法在容器内安全套用，"
        "也无法确认改的是同一仓库内的文件。",
        rule_repo_local_paths,
    ),
    Rule(
        "R6", "不含二进制 diff 块",
        "`Binary files ... differ` / `GIT binary patch` 不含完整二进制内容，"
        "仅凭 JSONL 无法物化；今天审计中 14 个新增 .png fixture 对应的测试"
        " 0/14 进入 oracle，正是这一类盲区（判据是 diff 形态，不是硬编码实例 id）。",
        rule_no_binary_diff,
    ),
)


def evaluate(rec: dict) -> tuple[bool, list[str], dict[str, str], str]:
    """返回 (是否准入, 失败规则 id 列表, 每条失败规则的说明, 首个失败规则 id)。"""
    failed: list[str] = []
    details: dict[str, str] = {}
    for rule in RULES:
        result = rule.evaluate(rec)
        if not result.ok:
            failed.append(rule.id)
            details[rule.id] = result.detail
    return (not failed), failed, details, (failed[0] if failed else "")


RULESET_FINGERPRINT = "\n".join(
    f"{rule.id}\t{rule.title}\t{rule.rationale}" for rule in RULES
)
