"""失效模式：真实会发生的坏输入/坏产物，都要以非零退出码失败，而不是静默通过。"""

import json

import pytest

from swe_subset.cli import main

from conftest import SYNTHETIC


def _write_jsonl(path, records):
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _build(input_path, out_dir):
    return main(["build", "--input", str(input_path), "--out", str(out_dir), "--label", "test"])


def _verify(out_dir):
    return main(
        [
            "verify",
            "--subset",
            str(out_dir / "subset.jsonl"),
            "--manifest",
            str(out_dir / "manifest.json"),
        ]
    )


# 失效模式 1：缺字段
def test_missing_required_field_is_rejected(tmp_path, valid_record):
    record = dict(valid_record)
    record.pop("patch")
    input_path = tmp_path / "instances.jsonl"
    _write_jsonl(input_path, [record])
    assert _build(input_path, tmp_path / "out") == 2


# 失效模式 2：字段类型错（数据源把 JSON 数组二次编码成字符串）
def test_wrong_field_type_is_rejected(tmp_path, valid_record):
    record = dict(valid_record, FAIL_TO_PASS=json.dumps(valid_record["FAIL_TO_PASS"]))
    input_path = tmp_path / "instances.jsonl"
    _write_jsonl(input_path, [record])
    assert _build(input_path, tmp_path / "out") == 2


# 失效模式 3：重复 instance_id
def test_duplicate_instance_id_is_rejected(tmp_path, valid_record):
    input_path = tmp_path / "instances.jsonl"
    _write_jsonl(input_path, [valid_record, dict(valid_record, repo="demo/other")])
    assert _build(input_path, tmp_path / "out") == 2


# 失效模式 4：输入被截断（最后一行不是完整 JSON）
def test_truncated_input_is_rejected(tmp_path, valid_record):
    input_path = tmp_path / "instances.jsonl"
    input_path.write_text(
        json.dumps(valid_record, ensure_ascii=False) + "\n" + '{"instance_id": "demo__demo-2",',
        encoding="utf-8",
    )
    assert _build(input_path, tmp_path / "out") == 2


# 失效模式 5：全部被排除 → 空子集，必须失败且不产出看起来成功的产物
def test_empty_subset_fails_without_writing_artifacts(tmp_path, valid_record):
    record = dict(valid_record, PASS_TO_PASS=[], instance_id="demo__demo-empty")
    input_path = tmp_path / "instances.jsonl"
    _write_jsonl(input_path, [record])
    out = tmp_path / "out"
    assert _build(input_path, out) == 3
    assert not (out / "subset.jsonl").exists()
    assert not (out / "manifest.json").exists()


# 失效模式 6：manifest 被篡改（条目哈希与 subset 不再对应）
def test_tampered_manifest_entry_is_detected(tmp_path):
    out = tmp_path / "out"
    assert _build(SYNTHETIC, out) == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["entries"][0]["sha256"] = "0" * 64
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert _verify(out) == 1


# 失效模式 7：subset 内容被改写（哈希/规范化/排序都会暴露）
def test_tampered_subset_is_detected(tmp_path):
    out = tmp_path / "out"
    assert _build(SYNTHETIC, out) == 0
    lines = (out / "subset.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    record["PASS_TO_PASS"] = []
    lines[0] = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    (out / "subset.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert _verify(out) == 1


# 失效模式 8：subset 被非规范重写（语义没变、字节变了）
def test_non_canonical_subset_is_detected(tmp_path):
    out = tmp_path / "out"
    assert _build(SYNTHETIC, out) == 0
    lines = (out / "subset.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[0])
    lines[0] = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=None, separators=(", ", ": "))
    (out / "subset.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert _verify(out) == 1


# 失效模式 9：manifest 缺字段
def test_manifest_missing_field_is_detected(tmp_path):
    out = tmp_path / "out"
    assert _build(SYNTHETIC, out) == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("manifest_sha256")
    (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert _verify(out) == 1


# 失效模式 10：输入文件被替换，但 manifest 仍声称对应旧输入
def test_changed_input_against_stale_manifest_is_detected(tmp_path):
    out = tmp_path / "out"
    assert _build(SYNTHETIC, out) == 0
    changed = tmp_path / "changed.jsonl"
    records = [json.loads(line) for line in SYNTHETIC.read_text(encoding="utf-8").splitlines()]
    records[0]["PASS_TO_PASS"] = ["a different regression test"]
    _write_jsonl(changed, records)
    assert main(
        [
            "verify",
            "--subset",
            str(out / "subset.jsonl"),
            "--manifest",
            str(out / "manifest.json"),
            "--input",
            str(changed),
        ]
    ) == 1
