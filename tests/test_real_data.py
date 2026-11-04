"""真实数据回归：本机附带的 SWE-bench_Multimodal dev（102 条）必须能端到端跑通。

这些断言只固定数据集事实（102 条、44 条空 P2P）与产物性质，不固定子集大小，
避免规则措辞微调时把测试改成"追着实现跑"。
"""

import json

import pytest

from swe_subset.cli import main

from conftest import REAL_DATA

pytestmark = pytest.mark.skipif(not REAL_DATA.exists(), reason="真实数据文件未随仓库提供")


def test_real_data_build_and_verify(tmp_path):
    out = tmp_path / "real"
    assert main(
        [
            "build",
            "--input",
            str(REAL_DATA),
            "--out",
            str(out),
            "--label",
            "swebench-multimodal-dev",
        ]
    ) == 0
    assert main(
        [
            "verify",
            "--subset",
            str(out / "subset.jsonl"),
            "--manifest",
            str(out / "manifest.json"),
            "--input",
            str(REAL_DATA),
        ]
    ) == 0

    audit = json.loads((out / "audit.json").read_text(encoding="utf-8"))
    stats = {item["id"]: item for item in audit["rules"]}

    # 数据集事实：102 条输入，44 条 PASS_TO_PASS 为空
    assert audit["input_rows"] == 102
    assert stats["R1"]["independent"] == 44

    records = [
        json.loads(line)
        for line in (out / "subset.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert records, "真实数据不应产出空子集"
    for record in records:
        assert [name.strip() for name in record["PASS_TO_PASS"] if name.strip()]
        assert record["FAIL_TO_PASS"]

    # 报告必须明确写出真实数据口径与不可证明项
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "swebench-multimodal-dev" in report
    assert "没有执行任何测试" in report


def test_real_data_is_byte_identical_across_runs(tmp_path):
    first = tmp_path / "run1"
    second = tmp_path / "run2"
    for out in (first, second):
        assert main(
            ["build", "--input", str(REAL_DATA), "--out", str(out), "--label", "swebench-multimodal-dev"]
        ) == 0
    for name in ("subset.jsonl", "manifest.json", "audit.json", "report.md"):
        assert (first / name).read_bytes() == (second / name).read_bytes()
