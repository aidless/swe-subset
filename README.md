# swe-subset

**可审计的 SWE-bench 子集构建器。零运行时第三方依赖（Python 3.10+ 标准库）。**

当前状态（本机实测，2026-11-04）：

- 真实 `SWE-bench_Multimodal` dev（102 条，本地数据，不入库）**端到端跑通**：准入 32 条、排除 70 条；
- 同一输入两次运行，`subset.jsonl` / `manifest.json` / `audit.json` / `report.md` **四份产物逐字节一致**；
- `pytest` **40 项通过**（含 2 项真实数据回归），覆盖 6 条准入规则与 10 条失效模式；
- 本机 Python 3.10 / 3.11 / 3.12 均实跑通过；**CI 跑的是 5 条合成 fixture，真实数据 102 条的结论是本机实测**；
- 未执行任何测试、未构建容器。

它解决的问题不是"再刷一个分数"，而是**先把评测集本身筛到可复核**：

> 在 `SWE-bench_Multimodal` dev 中，44/102（43.1%）实例的 `PASS_TO_PASS` 为空。
> 官方 `swebench==5.0.2` 在 `FAIL_ONLY` 评分下，这类实例只要目标测试通过，
> 其它测试失败也会被判 `RESOLVED_FULL`。另有 13 个实例的 `test_patch` 含二进制
> diff 块，仅凭 JSONL 无法 `git apply`。
> 证据来自同一天的 SWE-bench oracle 审计（本地报告，不入库）。

## 快速开始

```bash
git clone https://github.com/aidless/swe-subset.git && cd swe-subset
```

最小可跑命令（使用仓库自带的 5 条**合成 fixture**，离线可跑）：

```bash
python3 -m swe_subset build \
  --input tests/fixtures/synthetic_instances.jsonl \
  --out out --label synthetic-fixture

python3 -m swe_subset verify \
  --subset out/subset.jsonl --manifest out/manifest.json \
  --input tests/fixtures/synthetic_instances.jsonl
```

跑测试：

```bash
python3 -m pytest -q
```

复现"两次运行字节一致"（不依赖 pytest）：

```bash
python3 -m swe_subset build --input tests/fixtures/synthetic_instances.jsonl --out /tmp/a --label synthetic-fixture
python3 -m swe_subset build --input tests/fixtures/synthetic_instances.jsonl --out /tmp/b --label synthetic-fixture
diff -r /tmp/a /tmp/b
```

### 可选：在真实 102 条 dev 数据上跑

第三方数据集不随仓库分发。下载 `princeton-nlp/SWE-bench_Multimodal` 的 dev split 后，
按下节校验，再运行：

```bash
python3 -m swe_subset build \
  --input data/swebench_multimodal_dev.jsonl.gz \
  --out out-real --label swebench-multimodal-dev
```

## 六条准入规则

| ID | 判据 | 为什么 | 今天 dev 数据的独立命中 |
|---|---|---|---:|
| R1 | `PASS_TO_PASS` 去掉空白项后非空 | 空 P2P 没有任何回归信号，`FAIL_ONLY` 会把失败静默丢弃 | **44** |
| R2 | `FAIL_TO_PASS` 去掉空白项后非空 | 没有目标断言，补丁行为无法被区分 | 0 |
| R3 | 每条 F2P 都能在 `test_patch` 中定位 | F2P 与测试补丁对不上时，评分指向不可复核的目标 | **59** |
| R4 | 两个补丁的代码文件只对应一种语言，且无未知扩展名 | 跨语言需要多套工具链，统一镜像下不可复现 | 6 |
| R5 | 两个补丁非空、均有 diff 头、路径为仓库内相对路径 | 绝对路径 / `..` / 空补丁无法安全套用 | 0 |
| R6 | 无 `Binary files ... differ` / `GIT binary patch` 块 | 二进制 diff 不含完整内容，仅凭 JSONL 无法物化 | 13 |

R3 的定位方式（全部是字符串/路径匹配，不执行测试）：

1. `tests/test_x.py::test_name`：文件必须出现在被改路径中，末段测试名出现在 post-image 文本里；
2. fixture 路径（`.../vertical-pos.js`、`/base/...`、react-pdf 的整名路径）：路径必须出现在 `test_patch` 被改路径中；
3. 自由标题：`describe - it` 取最后一个 ` - ` 后的 it 标题精确命中（至少 3 个 token）；其它标题要求**至少 4 个 token 的连续后缀**命中。

判据来自 diff 形态与字段内容，没有写死任何实例 id。多条规则可能命中同一实例，
所以报告同时给出"独立命中"（单规则口径）与"顺序累计排除"（R1→R6 口径）。

## 产物

| 文件 | 内容 |
|---|---|
| `subset.jsonl` | 准入实例，按 `instance_id` 升序，规范 JSON（`sort_keys` + 紧凑分隔符） |
| `manifest.json` | 单条 sha256、全量 manifest hash、输入 sha256、规则集指纹、计数 |
| `audit.json` | 每条规则的独立/累计排除量，以及每个被排除实例的规则 id 与具体说明 |
| `report.md` | 人读审计报告，含"能证明什么 / 不能证明什么" |

哈希定义（可手算复核）：

- 单条实例：整条记录规范化 JSON 的 sha256；
- 全量 manifest：把 `instance_id<TAB>sha256\n` 按 id 排序拼接后取 sha256；
- 子集文件：`subset.jsonl` 原始字节的 sha256。

退出码：`0` 成功；`1` 校验失败；`2` 输入/读取错误；`3` 准入结果为空（不写出任何产物）。

## 数据来源（真实 vs 合成）

第三方数据集**不提交**进仓库（`data/` 已加入 `.gitignore`），按来源与哈希自行获取：

- 真实数据：HuggingFace `princeton-nlp/SWE-bench_Multimodal`，dev split，102 行。
  - 源 parquet（1,431,630 B）sha256：`617ebc06a461a9b28b7fed9cc6627ed96e87024a63f3a84ffe13cd63b64c7481`
  - 转为 JSONL 后 sha256：`ee2b38a50ea85890a7f01206a9ba83555d5eb90218277c67c74da566680a227f`
  - gzip 后（本机使用）sha256：`f2290f5119d1100b967507fe86ee0285103988a5a3667d665e245fc123322756`
  - 校验：`sha256sum data/swebench_multimodal_dev.jsonl.gz`
- 合成数据：`tests/fixtures/synthetic_instances.jsonl`，5 条，**明确是合成**，
  仅用于测试规则分支、失效模式与 CI，不代表任何真实 SWE-bench 统计。

CI 只跑合成 fixture；**真实数据 102 条上的 32/70、44 条空 P2P、两次运行字节一致等结论
均为本机实测**，clean clone 不会自动复现这些真实数据数字。

## 这份子集能证明什么

1. 本机输入上，32 条实例同时满足 6 条规则，每一条排除都能追溯到规则 id 与具体文本；
2. 子集不含空 `PASS_TO_PASS` 实例，不继承已审计到的 `FAIL_ONLY` 静默放行路径；
3. 子集不含二进制 diff 实例，不依赖 `image_assets` 恢复机制才能让测试补丁落地；
4. 产物可重放：同输入两次运行逐字节一致，第三方可用本工具独立复算出相同集合与哈希。

## 这份子集不能证明什么

1. **不能证明这些补丁能跑通。** 工具不执行测试、不构建容器，准入只是可评测性的必要条件；
2. **不能证明子集分数与全量 SWE-bench 分数可比。** 102 条只剩 32 条，分布已经变了；
3. **不能证明被排除实例的补丁是错的。** 它们只是 oracle 可复核性不足；
4. **不能证明测试覆盖完整。** 多文件 patch 只被单文件测试断言、新增单测未进 F2P 等缺口不在判定范围；
5. **不代表 SWE-bench 的分数分布。** 最终 32 条只覆盖 2 个仓库（wp-calypso 22、react-pdf 10），
   因此**不能代表 SWE-bench 的分数分布**，也不能外推到 Chart.js / marked / p5.js；
   若要代表性抽样，需放宽 R3 并重新评估 oracle 可复核性。量化：关闭 R3、仅保留
   R1/R2/R4/R5/R6 时，保留量从 32 条升至 **55 条**（wp-calypso 32、p5.js 12、react-pdf 11），
   仓库数从 2 个升到 3 个，但 oracle 可定位性不再被验证；
6. **R3 不是执行测试。** 定位失败只说明"无法从 test_patch 文本复核这个测试标识"。

## 边界

- 不联网、不下载大文件、不开 GPU；
- 不在本仓库内调用 `git apply` 或执行任何测试补丁；
- 第三方数据集不入库、不发 PyPI、不开 PR、不 force push；
- MIT License。
