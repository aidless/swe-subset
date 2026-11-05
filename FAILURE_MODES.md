# 失效模式

这里只写仓库里有测试、并且会以非零退出码失败的行为。不把未运行的评分器结果算进来。

## 空 PASS_TO_PASS（empty PASS_TO_PASS）

R1 把去掉空白后仍为空的 `PASS_TO_PASS` 判为排除。原因是名单里没有回归信号。空白字符串同样算空。

- 单条失败、其它实例仍可准入：该条记入 `audit.json`，退出码 `0`。合成 fixture 里的 `synthetic__demo-1002` 就是这种。
- 输入里每一条都被排除：退出码 `3`，并且不写 `subset.jsonl`、`manifest.json`、`audit.json`、`report.md`，避免留下一个看起来成功的空子集。

测试：`test_r1_empty_and_whitespace_only_fail`，`test_empty_subset_fails_without_writing_artifacts`。

本工具不调用 swebench，所以这里不声称某个版本的 `FAIL_ONLY` 会给空名单什么结论。

## 不可审计的 oracle（unauditable oracles）

两类输入无法只凭 JSONL 复核测试目标，都会被排除，退出码仍可以是 `0`（只要还有别的实例准入）：

- R3：某条 `FAIL_TO_PASS` 不能在 `test_patch` 里定位（nodeid 的文件或测试名不在、标题过短、或补丁没有 `diff --git` 块）。定位是字符串和路径匹配，不是跑测试。
- R6：`patch` 或 `test_patch` 含 `Binary files ... differ` 或 `GIT binary patch`。块里没有完整文件字节，不能从 JSONL 还原该文件。本仓库不调用 `git apply`。

排除不表示补丁写错，只表示按这两条规则无法审计 oracle。

测试：`test_r3_title_too_short_fails_conservatively`，`test_r3_empty_test_patch_fails`，`test_r6_binary_files_block_fails`，`test_r6_git_binary_patch_fails`。

## 哈希不一致（hash mismatch）

`verify` 在下列情况退出码 `1`，并且不把结果说成通过：

| 情况 | 测试 |
|---|---|
| 某条 `manifest.entries[].sha256` 与子集记录不一致 | `test_tampered_manifest_entry_is_detected` |
| 子集记录内容被改写 | `test_tampered_subset_is_detected` |
| 语义相同但字节不再是规范 JSON | `test_non_canonical_subset_is_detected` |
| manifest 缺少 `manifest_sha256` 等必需字段 | `test_manifest_missing_field_is_detected` |
| `--input` 的 sha256 与 manifest 记录的输入哈希不同 | `test_changed_input_against_stale_manifest_is_detected` |
| `ruleset_sha256` 与当前代码里的规则集指纹不同 | `test_ruleset_fingerprint_mismatch_is_detected` |

全量 manifest hash 是排序后的 `instance_id<TAB>sha256\n` 的 sha256。条目哈希被改而外层 `manifest_sha256` 未重算时，条目检查和全量 hash 检查都会失败。

## 输入本身不可读

这些不是 oracle 问题。`build` 直接退出码 `2`，不写准入产物：

- `test_missing_required_field_is_rejected`
- `test_wrong_field_type_is_rejected`
- `test_duplicate_instance_id_is_rejected`
- `test_truncated_input_is_rejected`
