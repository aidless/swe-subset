"""端到端：构建、产物结构、两次运行字节一致、manifest 可校验。"""

import json

from swe_subset.cli import main
from swe_subset.manifest import instance_hash, manifest_hash

from conftest import SYNTHETIC

OUTPUT_FILES = ("subset.jsonl", "manifest.json", "audit.json", "report.md")


def _build(out_dir, label="synthetic-fixture"):
    return main(["build", "--input", str(SYNTHETIC), "--out", str(out_dir), "--label", label])


def _read_all(out_dir):
    return {name: (out_dir / name).read_bytes() for name in OUTPUT_FILES}


def test_build_synthetic_admits_expected_instances(tmp_path, capsys):
    out = tmp_path / "out"
    assert _build(out) == 0

    audit = json.loads((out / "audit.json").read_text(encoding="utf-8"))
    admitted = [item["instance_id"] for item in audit["admitted"]]
    assert admitted == ["synthetic__demo-1001", "synthetic__demo-1003"]

    excluded = {item["instance_id"]: item["primary_rule"] for item in audit["excluded"]}
    assert excluded == {
        "synthetic__demo-1002": "R1",
        "synthetic__demo-1004": "R6",
        "synthetic__demo-1005": "R4",
    }
    assert audit["input_rows"] == 5
    assert audit["admitted_count"] == 2
    assert audit["excluded_count"] == 3


def test_all_output_files_are_byte_identical_across_runs(tmp_path):
    first = tmp_path / "run1"
    second = tmp_path / "run2"
    assert _build(first) == 0
    assert _build(second) == 0
    assert _read_all(first) == _read_all(second)


def test_manifest_matches_subset_and_verifies(tmp_path):
    out = tmp_path / "out"
    assert _build(out) == 0
    assert main(
        [
            "verify",
            "--subset",
            str(out / "subset.jsonl"),
            "--manifest",
            str(out / "manifest.json"),
            "--input",
            str(SYNTHETIC),
        ]
    ) == 0

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    records = [
        json.loads(line)
        for line in (out / "subset.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["instance_id"] for item in manifest["entries"]] == [
        record["instance_id"] for record in records
    ]
    assert [item["sha256"] for item in manifest["entries"]] == [
        instance_hash(record) for record in records
    ]
    assert manifest["manifest_sha256"] == manifest_hash(
        [(item["instance_id"], item["sha256"]) for item in manifest["entries"]]
    )


def test_subset_lines_are_canonical_json(tmp_path):
    out = tmp_path / "out"
    assert _build(out) == 0
    for line in (out / "subset.jsonl").read_bytes().splitlines():
        record = json.loads(line)
        canonical = json.dumps(
            record, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        assert line == canonical


def test_report_states_proof_boundaries(tmp_path):
    out = tmp_path / "out"
    assert _build(out, label="synthetic-fixture") == 0
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "这份子集能证明什么" in report
    assert "这份子集不能证明什么" in report
    assert "不能证明这些补丁能跑通" in report
    assert "synthetic-fixture" in report
