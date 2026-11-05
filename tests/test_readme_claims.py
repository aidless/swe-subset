"""README、FAILURE_MODES 与 CI 工作流不得漂离当前测试树。"""

import ast
import re
from pathlib import Path

from swe_subset.cli import EXIT_EMPTY, EXIT_INPUT, EXIT_OK, EXIT_VERIFY_FAILED
from swe_subset.rules import RULES

from conftest import DOCUMENTED_GZIP_SHA256_RE, ROOT, SYNTHETIC

README = (ROOT / "README.md").read_text(encoding="utf-8")
FAILURES = (ROOT / "FAILURE_MODES.md").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

MACHINE_PATH = re.compile(r"(/Users/|/home/|/private/var|/tmp/|[A-Za-z]:\\)")
PUBLISHED_DOCS = (README, FAILURES, CI)


def _item_path(item) -> Path:
    path = getattr(item, "path", None)
    if path is None:
        path = item.fspath
    return Path(str(path))


def _problem_lines() -> list[str]:
    lines = README.splitlines()
    assert lines[0] == "# swe-subset"
    assert lines[1] == ""
    body: list[str] = []
    for line in lines[2:]:
        if line.startswith("## "):
            break
        if line.strip():
            body.append(line)
    return body


def test_problem_statement_is_at_most_three_lines():
    body = _problem_lines()
    assert 1 <= len(body) <= 3
    text = "\n".join(body)
    assert "六条只读规则" in text
    assert len(RULES) == 6
    # 开篇只写问题，不写未进 CI 的数据集计数。
    assert "102" not in text
    assert "44" not in text


def _calls_parametrize_or_skip(source: str) -> list[str]:
    """看语法树，避免本文件的说明文字把自己判成漂移。"""
    found: list[str] = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = ast.unparse(node.func)
        if func.endswith("parametrize") or func.endswith("skipif") or func.endswith(".skip"):
            found.append(func)
    return found


def test_documented_counts_match_collected_tests(request):
    items = list(request.session.items)
    total = len(items)
    gated = [item for item in items if _item_path(item).name == "test_real_data.py"]
    failure = [item for item in items if _item_path(item).name == "test_failure_modes.py"]
    rows = [line for line in SYNTHETIC.read_text(encoding="utf-8").splitlines() if line.strip()]

    for path in (ROOT / "tests").glob("test_*.py"):
        calls = _calls_parametrize_or_skip(path.read_text(encoding="utf-8"))
        assert not any(name.endswith("parametrize") for name in calls)
        if path.name != "test_real_data.py":
            assert not calls

    expected = (
        f"树内测试函数 {total} 个。"
        f"无 `data/swebench_multimodal_dev.jsonl.gz` 时跳过 {len(gated)} 个"
        f"（都在 `tests/test_real_data.py`），因此 CI 执行 {total - len(gated)} 个。"
        f"失效模式测试 {len(failure)} 个。合成 fixture {len(rows)} 行。"
    )
    assert expected in README
    assert "上述计数由 `tests/test_readme_claims.py` 对照 pytest 收集结果" in README


def test_evidence_boundaries_name_ci_local_and_published():
    assert "## 证据边界" in README
    assert "| CI |" in README
    assert "| 本机 |" in README
    assert "| 仓库发布物 |" in README
    assert "这些数字不是 CI 结果" in README
    assert "CI 不下载数据集" in README
    assert "CI 不校验这个哈希" in README
    assert "不代表任何 SWE-bench 统计" in README
    assert "tests/fixtures/synthetic_instances.jsonl" in README
    assert "不需要下载数据集" in README
    assert "退出码：`0` 成功；`1` 校验失败；`2` 输入错误；`3` 准入为空。" in README
    assert (EXIT_OK, EXIT_VERIFY_FAILED, EXIT_INPUT, EXIT_EMPTY) == (0, 1, 2, 3)
    assert len(DOCUMENTED_GZIP_SHA256_RE.findall(README)) == 1
    for stale in ("wp-calypso", "准入 32", "55 条", "43.1%", "40 项通过"):
        assert stale not in README
        assert stale not in FAILURES


def test_no_badges_pypi_or_machine_absolute_paths():
    for text in PUBLISHED_DOCS:
        lowered = text.lower()
        assert "shields.io" not in lowered
        assert "pypi" not in lowered
        assert "badge" not in lowered
        assert "![" not in text
        assert MACHINE_PATH.search(text) is None
    for path in (ROOT / "swe_subset").glob("*.py"):
        assert MACHINE_PATH.search(path.read_text(encoding="utf-8")) is None


def test_failure_modes_name_checked_behaviors(request):
    for phrase in (
        "空 PASS_TO_PASS",
        "empty PASS_TO_PASS",
        "不可审计的 oracle",
        "unauditable oracles",
        "哈希不一致",
        "hash mismatch",
    ):
        assert phrase in FAILURES

    names = {
        item.name
        for item in request.session.items
        if _item_path(item).name == "test_failure_modes.py"
    }
    assert names, "失效模式测试没有被收集到"
    for name in sorted(names):
        assert f"`{name}`" in FAILURES

    collected = {item.name for item in request.session.items}
    # 至少再带一段下划线，避免把字段名 test_patch 当成测试函数。
    cited = set(re.findall(r"`(test_[a-z0-9]+(?:_[a-z0-9]+)+)`", FAILURES))
    missing = sorted(cited - collected)
    assert not missing


def test_ci_runs_only_the_in_repo_synthetic_fixture():
    assert "tests/fixtures/synthetic_instances.jsonl" in CI
    assert "out/ci-a" in CI
    assert "out/ci-b" in CI
    assert "/tmp/" not in CI
    lowered = CI.lower()
    for token in ("huggingface", "princeton-nlp", "wget", "curl "):
        assert token not in lowered
