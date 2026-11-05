"""审计报告渲染（Markdown）。

报告里的每个数字都来自本次运行，不含时间戳和主机信息，因此同一输入
两次生成的报告也字节一致。措辞区分"本工具证明了什么"与"没有证明什么"。
"""

from __future__ import annotations

from .rules import RULES


def _pct(part: int, total: int) -> str:
    if total == 0:
        return "0.0%"
    return f"{part / total * 100:.1f}%"


def render_report(
    *,
    label: str,
    input_sha256: str,
    rows: int,
    admitted: list[dict],
    excluded: list[dict],
    rule_stats: list[dict],
    manifest_hash: str,
    subset_sha256: str,
    ruleset_sha256: str,
    repo_counts: list[tuple[str, int]],
    input_repo_counts: list[tuple[str, int]],
) -> str:
    rule_by_id = {rule.id: rule for rule in RULES}
    lines: list[str] = []

    lines.append("# SWE-bench 子集审计报告")
    lines.append("")
    lines.append("> 本报告由 `swe_subset build` 生成，不含时间戳；同一输入可重放为字节一致的结果。")
    lines.append("")
    lines.append("## 0. 结论")
    lines.append("")
    lines.append(f"- 输入：`{label}`，{rows} 条实例，输入 sha256 `{input_sha256}`")
    lines.append(
        f"- 准入 **{len(admitted)}** 条，排除 **{len(excluded)}** 条（{_pct(len(excluded), rows)}）"
    )
    if rule_stats:
        top = max(rule_stats, key=lambda item: (item["independent"], item["waterfall"]))
        if top["independent"] > 0:
            lines.append(
                f"- 排除量最大的单条规则是 **{top['id']} {rule_by_id[top['id']].title}**，"
                f"独立命中 {top['independent']} 条（{_pct(top['independent'], rows)}）"
            )
    lines.append(f"- 全量 manifest hash：`{manifest_hash}`")
    lines.append(f"- 子集文件 sha256：`{subset_sha256}`")
    lines.append(f"- 规则集指纹 sha256：`{ruleset_sha256}`")
    lines.append("- 本次运行**没有执行任何测试**，所有判断都只基于实例字段与补丁文本。")
    lines.append("")
    lines.append("## 1. 准入规则与排除量")
    lines.append("")
    lines.append("| 规则 | 判据 | 独立命中 | 顺序累计排除 |")
    lines.append("|---|---|---:|---:|")
    for item in rule_stats:
        rule = rule_by_id[item["id"]]
        lines.append(
            f"| {rule.id} {rule.title} | {item['criterion']} | {item['independent']} | {item['waterfall']} |"
        )
    lines.append("")
    lines.append("说明：`独立命中` 是只看该规则时的排除数，多条规则可以命中同一实例，因此独立命中相加可以大于总排除数。"
                 "`顺序累计排除` 是按 R1→R6 判定时新增加的排除数，这一列相加等于总排除数。")
    lines.append("")
    lines.append("## 2. 排除明细")
    lines.append("")
    if excluded:
        lines.append("| instance_id | repo | 首个失败规则 | 全部失败规则 | 说明 |")
        lines.append("|---|---|---|---|---|")
        for item in excluded:
            detail = item["details"].get(item["primary_rule"], "")
            detail = detail.replace("|", "\\|")
            lines.append(
                f"| `{item['instance_id']}` | `{item['repo']}` | {item['primary_rule']} | "
                f"{', '.join(item['failed_rules'])} | {detail} |"
            )
    else:
        lines.append("无（输入中所有实例都通过了全部规则）。")
    lines.append("")
    lines.append("## 3. 准入实例")
    lines.append("")
    lines.append("仓库分布：")
    lines.append("")
    lines.append("| repo | 准入数 | 输入数 |")
    lines.append("|---|---:|---:|")
    input_by_repo = dict(input_repo_counts)
    for repo, count in repo_counts:
        lines.append(f"| `{repo}` | {count} | {input_by_repo.get(repo, 0)} |")
    lines.append("")
    if admitted:
        for item in admitted:
            lines.append(f"- `{item['instance_id']}`（`{item['repo']}`）")
    else:
        lines.append("无。")
    lines.append("")
    lines.append("## 4. 这份子集能证明什么")
    lines.append("")
    lines.append(
        f"1. 在输入 `{label}` 上，这 {len(admitted)} 条实例**同时满足** 6 条准入规则；"
        f"每一条排除都能追溯到规则 id 与具体文本（见第 2 节）。"
    )
    empty_p2p = next((item["independent"] for item in rule_stats if item["id"] == "R1"), 0)
    lines.append(
        f"2. 输入中 **{empty_p2p}** 条 `PASS_TO_PASS` 为空（或只有空白）的实例被 R1 排除，"
        "子集里不保留空回归名单。本工具不运行外部评分器，因此这里不判断"
        "某个 swebench 版本会给这些实例什么结论。"
    )
    lines.append(
        "3. 子集**不含**二进制 diff 块，因此这些补丁里被改文件的文本都在 diff 中。"
        "本工具不检查 `image_assets`，也不把补丁应用到仓库。"
    )
    lines.append(
        "4. 四份产物不含时间戳、主机名或绝对路径，以便同一输入的下一次运行写出相同字节。"
        "本文件只记录这一次写出的字节。"
    )
    lines.append(
        "5. 任何第三方拿到同一输入文件和本工具，可以独立复算出**完全相同**的准入集合与哈希。"
    )
    lines.append("")
    lines.append("## 5. 这份子集不能证明什么")
    lines.append("")
    lines.append(
        "1. **不能证明这些补丁能跑通。** 本工具不执行测试、不构建容器，"
        "`FAIL_TO_PASS` 可定位、语言单一、路径合法，都只是可评测性的必要条件。"
    )
    lines.append(
        f"2. **不能证明子集分数与全量 SWE-bench 分数可比。** 子集是过滤后的集合："
        f"输入 {rows} 条留下 {len(admitted)} 条，其中 {empty_p2p} 条空 P2P 实例被排除。"
    )
    lines.append(
        "3. **不能证明被排除实例的补丁是错的。** 它们只是 oracle 可复核性不足，"
        "不是补丁质量差。"
    )
    lines.append(
        "4. **不能证明测试覆盖完整。** 多文件 patch 只被单文件测试断言、"
        "新增单测未进 `FAIL_TO_PASS` 等覆盖缺口不在本工具的判定范围内。"
    )
    lines.append(
        f"5. **仓库覆盖有限。** 输入覆盖 {len(input_repo_counts)} 个仓库，"
        f"准入集合覆盖 {len(repo_counts)} 个；未覆盖的仓库不能由本子集代表。"
    )
    lines.append(
        "6. **R3 是字符串/路径匹配，不是执行测试。** 定位失败只说明"
        "“无法从 test_patch 文本复核这个测试标识”，不等于该测试在仓库中不存在。"
    )
    lines.append(
        "7. **本报告不对应任何模型成绩。** 它只描述评测集本身的准入条件，"
        "不含任何提交、候选补丁或榜单数据。"
    )
    lines.append("")
    lines.append("## 6. 复现命令")
    lines.append("")
    lines.append("```bash")
    lines.append("python3 -m swe_subset build --input <instances.jsonl> --out <out-dir> --label <label>")
    lines.append("python3 -m swe_subset verify --subset <out-dir>/subset.jsonl --manifest <out-dir>/manifest.json")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)
