"""命令行入口：`python3 -m swe_subset build|verify`。"""

from __future__ import annotations

import argparse
import json
import os
import sys

from . import RULESET_VERSION, SCHEMA_VERSION, __version__
from .manifest import (
    canonical_bytes,
    file_sha256,
    instance_hash,
    json_bytes,
    manifest_hash,
    sha256_hex,
    subset_bytes,
)
from .report import render_report
from .rules import RULES, RULESET_FINGERPRINT, evaluate
from .schema import InputError, load_instances

CRITERIA = {
    "R1": "PASS_TO_PASS 去掉空白项后非空",
    "R2": "FAIL_TO_PASS 去掉空白项后非空",
    "R3": "全部 F2P 可在 test_patch 定位（nodeid / fixture 路径 / it 标题或 ≥4-token 后缀，含上下文行）",
    "R4": "patch+test_patch 的代码文件只对应一种语言，且无未知扩展名",
    "R5": "两个补丁非空、均有 diff 头、被改路径为仓库内相对路径",
    "R6": "无 `Binary files ... differ` / `GIT binary patch` 块",
}

EXIT_OK = 0
EXIT_INPUT = 2
EXIT_EMPTY = 3
EXIT_VERIFY_FAILED = 1


def _ruleset_sha256() -> str:
    return sha256_hex(RULESET_FINGERPRINT.encode("utf-8"))


def cmd_build(args: argparse.Namespace) -> int:
    try:
        records = load_instances(args.input)
    except InputError as exc:
        print(f"输入错误：{exc}", file=sys.stderr)
        return EXIT_INPUT

    admitted_recs: list[dict] = []
    excluded: list[dict] = []
    failed_ids: list[list[str]] = []
    for rec in records:
        ok, failed, details, primary = evaluate(rec)
        failed_ids.append(failed)
        if ok:
            admitted_recs.append(rec)
        else:
            excluded.append(
                {
                    "instance_id": rec["instance_id"],
                    "repo": rec["repo"],
                    "primary_rule": primary,
                    "failed_rules": failed,
                    "details": details,
                }
            )

    admitted_recs.sort(key=lambda rec: rec["instance_id"])
    excluded.sort(key=lambda item: item["instance_id"])

    if not admitted_recs:
        print(
            f"准入结果为空：{len(records)} 条输入全部被排除，未写出任何产物。"
            f"（按规则逐条复核后仍为空被视为失败，避免产出一个看起来成功的空子集）",
            file=sys.stderr,
        )
        return EXIT_EMPTY

    input_sha = file_sha256(args.input)
    subset = subset_bytes(admitted_recs)
    subset_sha = sha256_hex(subset)
    entries = sorted((rec["instance_id"], instance_hash(rec)) for rec in admitted_recs)
    manifest_digest = manifest_hash(entries)

    rule_stats = []
    for rule in RULES:
        independent = sum(1 for failed in failed_ids if rule.id in failed)
        waterfall = sum(1 for item in excluded if item["primary_rule"] == rule.id)
        rule_stats.append(
            {
                "id": rule.id,
                "title": rule.title,
                "rationale": rule.rationale,
                "criterion": CRITERIA[rule.id],
                "independent": independent,
                "waterfall": waterfall,
            }
        )

    audit = {
        "schema_version": SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "ruleset_sha256": _ruleset_sha256(),
        "dataset_label": args.label,
        "input_sha256": input_sha,
        "input_rows": len(records),
        "admitted_count": len(admitted_recs),
        "excluded_count": len(excluded),
        "rules": rule_stats,
        "admitted": [
            {"instance_id": rec["instance_id"], "repo": rec["repo"]} for rec in admitted_recs
        ],
        "excluded": excluded,
    }

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "ruleset_version": RULESET_VERSION,
        "ruleset_sha256": _ruleset_sha256(),
        "dataset_label": args.label,
        "input_sha256": input_sha,
        "input_rows": len(records),
        "admitted": len(admitted_recs),
        "excluded": len(excluded),
        "subset_sha256": subset_sha,
        "entries": [{"instance_id": iid, "sha256": digest} for iid, digest in entries],
        "manifest_sha256": manifest_digest,
    }

    report = render_report(
        label=args.label,
        input_sha256=input_sha,
        rows=len(records),
        admitted=audit["admitted"],
        excluded=excluded,
        rule_stats=rule_stats,
        manifest_hash=manifest_digest,
        subset_sha256=subset_sha,
        ruleset_sha256=_ruleset_sha256(),
        repo_counts=sorted(_count_by_repo(admitted_recs).items()),
        input_repo_counts=sorted(_count_by_repo(records).items()),
    )

    os.makedirs(args.out, exist_ok=True)
    _write(os.path.join(args.out, "subset.jsonl"), subset)
    _write(os.path.join(args.out, "manifest.json"), json_bytes(manifest))
    _write(os.path.join(args.out, "audit.json"), json_bytes(audit))
    _write(os.path.join(args.out, "report.md"), report.encode("utf-8"))

    print(f"输入：{args.input}（{len(records)} 条，label={args.label}）")
    print(f"准入 {len(admitted_recs)} 条，排除 {len(excluded)} 条")
    for item in rule_stats:
        print(
            f"  {item['id']} 独立 {item['independent']:>3} 条 / 顺序累计 "
            f"{item['waterfall']:>3} 条  {item['title']}"
        )
    print(f"产物：{args.out}")
    print(f"manifest_sha256：{manifest_digest}")
    print(f"subset_sha256：{subset_sha}")
    return EXIT_OK


def _write(path: str, data: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(data)


def _count_by_repo(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in records:
        repo = rec["repo"]
        counts[repo] = counts.get(repo, 0) + 1
    return counts


def cmd_verify(args: argparse.Namespace) -> int:
    problems: list[str] = []

    try:
        with open(args.manifest, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        with open(args.subset, "rb") as fh:
            subset_bytes_raw = fh.read()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"读取失败：{exc}", file=sys.stderr)
        return EXIT_INPUT

    required = {
        "schema_version",
        "ruleset_version",
        "ruleset_sha256",
        "dataset_label",
        "input_sha256",
        "input_rows",
        "admitted",
        "excluded",
        "subset_sha256",
        "entries",
        "manifest_sha256",
    }
    missing = sorted(required - set(manifest))
    if missing:
        problems.append(f"manifest 缺少字段：{', '.join(missing)}")

    if not subset_bytes_raw.endswith(b"\n") and subset_bytes_raw:
        problems.append("subset.jsonl 末尾缺少换行符（不是本工具产出的规范形态）")

    subset_sha = sha256_hex(subset_bytes_raw)
    if manifest.get("subset_sha256") != subset_sha:
        problems.append(
            f"subset.jsonl sha256 不匹配：manifest={manifest.get('subset_sha256')} 实际={subset_sha}"
        )

    parsed_records: list[dict] = []
    for lineno, line in enumerate(subset_bytes_raw.splitlines(), start=1):
        if not line:
            problems.append(f"subset.jsonl 第 {lineno} 行为空行")
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"subset.jsonl 第 {lineno} 行不是合法 JSON：{exc.msg}")
            continue
        if canonical_bytes(rec) != line:
            problems.append(
                f"subset.jsonl 第 {lineno} 行不是规范 JSON（键未排序或含多余空白），可能被手工改写"
            )
        parsed_records.append(rec)

    actual_entries: list[tuple[str, str]] = []
    ids: list[str] = []
    for rec in parsed_records:
        iid = rec.get("instance_id")
        if not isinstance(iid, str) or not iid:
            problems.append("subset.jsonl 中存在缺失 instance_id 的记录")
            continue
        ids.append(iid)
        actual_entries.append((iid, instance_hash(rec)))

    if ids != sorted(ids):
        problems.append("subset.jsonl 未按 instance_id 排序")
    if len(ids) != len(set(ids)):
        problems.append("subset.jsonl 存在重复 instance_id")

    entry_list = manifest.get("entries")
    if not isinstance(entry_list, list):
        problems.append("manifest.entries 必须是列表")
    else:
        declared = []
        for entry in entry_list:
            if not isinstance(entry, dict) or "instance_id" not in entry or "sha256" not in entry:
                problems.append("manifest.entries 中存在结构错误的条目")
                continue
            declared.append((entry["instance_id"], entry["sha256"]))
        if declared != sorted(declared):
            problems.append("manifest.entries 未按 instance_id 排序")
        if declared != actual_entries:
            problems.append("manifest.entries 与 subset.jsonl 的记录哈希不一致（内容被篡改或混入多余记录）")
        if manifest.get("admitted") != len(declared):
            problems.append(
                f"manifest.admitted={manifest.get('admitted')} 与 entries 数量 {len(declared)} 不一致"
            )
        recomputed = manifest_hash(declared)
        if manifest.get("manifest_sha256") != recomputed:
            problems.append(
                f"全量 manifest hash 不匹配：manifest={manifest.get('manifest_sha256')} 实际={recomputed}"
            )

    ruleset_now = _ruleset_sha256()
    if manifest.get("ruleset_sha256") != ruleset_now:
        problems.append(
            f"规则集指纹不一致：manifest={manifest.get('ruleset_sha256')} 当前工具={ruleset_now}"
        )

    if args.input:
        if not os.path.isfile(args.input):
            problems.append(f"--input 指定的文件不存在：{args.input}")
        else:
            actual_input_sha = file_sha256(args.input)
            if manifest.get("input_sha256") != actual_input_sha:
                problems.append(
                    f"输入 sha256 不匹配：manifest={manifest.get('input_sha256')} 实际={actual_input_sha}"
                )

    if problems:
        print("校验失败：")
        for item in problems:
            print(f"  - {item}")
        return EXIT_VERIFY_FAILED

    print(f"校验通过：{len(parsed_records)} 条记录，manifest_sha256={manifest.get('manifest_sha256')}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="swe_subset",
        description="可审计的 SWE-bench 子集构建器（仅标准库）",
    )
    parser.add_argument("--version", action="version", version=f"swe_subset {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="构建子集、manifest 与审计报告")
    build.add_argument("--input", required=True, help="instances JSONL（支持 .gz）")
    build.add_argument("--out", required=True, help="输出目录")
    build.add_argument("--label", default="unspecified", help="数据集标签，写入报告与 manifest")
    build.set_defaults(func=cmd_build)

    verify = sub.add_parser("verify", help="校验 subset.jsonl 与 manifest.json 的一致性")
    verify.add_argument("--subset", required=True, help="subset.jsonl")
    verify.add_argument("--manifest", required=True, help="manifest.json")
    verify.add_argument("--input", default=None, help="可选：同时校验输入文件 sha256")
    verify.set_defaults(func=cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
