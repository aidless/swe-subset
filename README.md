# swe-subset

SWE-bench 的 JSONL 有时给不出可复核的测试 oracle：`PASS_TO_PASS` 为空就没有回归名单，`FAIL_TO_PASS` 对不上 `test_patch` 就无法审计目标，二进制 diff 也不能从文本还原文件。
`swe-subset` 用六条只读规则留下同时满足这些条件的实例，并为每条排除记录规则 id 和依据；同一输入两次运行，产物逐字节一致。
它不执行测试、不构建容器，因此不能证明补丁能跑通，也不能把子集上的分数当作全量 SWE-bench 成绩。

## 证据边界

| 范围 | 实际覆盖 |
|---|---|
| CI | `.github/workflows/ci.yml` 在 Python 3.10、3.11、3.12 上安装 pytest 并运行仓库内测试。没有 `data/` 时 `tests/test_real_data.py` 整文件跳过。然后对仓库内的 5 行合成 fixture 构建两次、`diff`、再 `verify`。CI 不下载数据集。工作流只声明这个矩阵；本文不记载某一次 Actions 是否成功。 |
| 本机 | 只有磁盘上存在 `data/swebench_multimodal_dev.jsonl.gz` 时，`tests/test_real_data.py` 才运行。该测试固定输入 102 行，以及 R1 独立命中 44（空 `PASS_TO_PASS`）。准入条数和仓库分布不固定，以当次 `report.md` 为准。这些数字不是 CI 结果。 |
| 仓库发布物 | 源码、合成 fixture、测试、本文件、`FAILURE_MODES.md`、MIT 许可证。不含第三方数据集，不含 `subset.jsonl` 等构建产物，不含模型分数。 |

树内测试函数 48 个。无 `data/swebench_multimodal_dev.jsonl.gz` 时跳过 3 个（都在 `tests/test_real_data.py`），因此 CI 执行 45 个。失效模式测试 11 个。合成 fixture 5 行。

上述计数由 `tests/test_readme_claims.py` 对照 pytest 收集结果。对不上就失败。

## 离线路径（合成 fixture）

构建和校验只用 Python 3.10+ 标准库。不需要安装本包，不需要下载数据集。在仓库根目录：

```bash
git clone https://github.com/aidless/swe-subset.git && cd swe-subset

python3 -m swe_subset build \
  --input tests/fixtures/synthetic_instances.jsonl \
  --out out/synthetic --label synthetic-fixture

python3 -m swe_subset verify \
  --subset out/synthetic/subset.jsonl \
  --manifest out/synthetic/manifest.json \
  --input tests/fixtures/synthetic_instances.jsonl
```

这 5 行是手写例子，用来覆盖规则分支。`tests/test_build.py` 固定这次运行准入 2 条、排除 3 条。该结果不代表任何 SWE-bench 统计。

同一合成输入的两次产物（相对路径）：

```bash
python3 -m swe_subset build --input tests/fixtures/synthetic_instances.jsonl --out out/run-a --label synthetic-fixture
python3 -m swe_subset build --input tests/fixtures/synthetic_instances.jsonl --out out/run-b --label synthetic-fixture
diff -r out/run-a out/run-b
```

`pytest` 只属于测试，不是构建依赖。CI 会从网络安装 pytest。没有网络时，上面的 `build` / `verify` 仍是离线路径，测试步骤不是。

```bash
python3 -m pytest -q
```

## 六条准入规则

某份输入上每条规则命中多少，只出现在那次 `report.md` 里。下表不列本机命中数。

| ID | 判据 | 为什么 |
|---|---|---|
| R1 | `PASS_TO_PASS` 去掉空白项后非空 | 空名单没有任何回归信号 |
| R2 | `FAIL_TO_PASS` 去掉空白项后非空 | 没有目标断言，补丁行为无法区分 |
| R3 | 每条 F2P 都能在 `test_patch` 中定位 | 对不上测试补丁时，评分目标不可复核 |
| R4 | 两个补丁的代码文件只对应一种语言，且无未知扩展名 | 跨语言需要多套工具链 |
| R5 | 两个补丁非空、均有 diff 头、路径为仓库内相对路径 | 绝对路径、`..` 或空补丁无法安全套用 |
| R6 | 无 `Binary files ... differ` / `GIT binary patch` 块 | 这类 diff 没有完整文件字节，不能只凭 JSONL 还原 |

R3 只做字符串和路径匹配，不执行测试：

1. `tests/test_x.py::test_name`：文件必须出现在被改路径中，末段测试名出现在 post-image 文本里；
2. fixture 路径（以带扩展名的路径结尾，或去掉 `/base/` 前缀后是路径）：路径必须出现在 `test_patch` 被改路径中；
3. 自由标题：`describe - it` 取最后一个 ` - ` 后的 it 标题精确命中（至少 3 个 token）；其它标题要求至少 4 个 token 的连续后缀命中。

判据来自 diff 形态和字段内容，不写死实例 id。一条实例可以同时命中多条规则。报告同时给出独立命中和按 R1→R6 的顺序累计排除。

## 产物

| 文件 | 内容 |
|---|---|
| `subset.jsonl` | 准入实例，按 `instance_id` 升序，规范 JSON（`sort_keys` + 紧凑分隔符） |
| `manifest.json` | 单条 sha256、全量 manifest hash、输入 sha256、规则集指纹、计数 |
| `audit.json` | 每条规则的独立命中和顺序累计排除，以及每个被排除实例的规则 id 与说明 |
| `report.md` | 人读报告，区分本次输入能证明的事和不能证明的事 |

哈希可以手算：

- 单条实例：整条记录规范化 JSON 的 sha256；
- 全量 manifest：把 `instance_id<TAB>sha256\n` 按 id 排序拼接后取 sha256；
- 子集文件：`subset.jsonl` 原始字节的 sha256。

退出码：`0` 成功；`1` 校验失败；`2` 输入错误；`3` 准入为空。

空 `PASS_TO_PASS`、无法从 JSONL 审计的 oracle、哈希对不上，见 [`FAILURE_MODES.md`](FAILURE_MODES.md)。

## 能证明什么

1. 对你给出的输入，准入实例同时满足六条规则；每条排除能追溯到规则 id 和说明。
2. 空的 `PASS_TO_PASS` 不会留在子集里。
3. 含二进制 diff 块的实例不会留在子集里。
4. 在合成 fixture 上，CI 检查两次构建逐字节一致，并且 `verify` 通过。同一检查在真实数据上只在本机文件存在时运行。

## 不能证明什么

1. **不能证明这些补丁能跑通。** 工具不执行测试，不构建容器。
2. **不能证明子集分数与全量 SWE-bench 可比。** 过滤会改变分布。具体留下多少条，只写在当次报告里。
3. **不能证明被排除实例的补丁是错的。** 排除只说明 oracle 无法按这些规则复核。
4. **不能证明测试覆盖完整。** 多文件 patch 只被单文件测试断言、新增测试未进 `FAIL_TO_PASS`，都不在判定范围内。
5. **不能用准入集合代表整个 SWE-bench。** 仓库覆盖以当次报告的仓库表为准。
6. **R3 不是执行测试。** 定位失败只说明无法从 `test_patch` 文本复核这个测试标识。
7. **没有模型成绩。** 仓库不发布提交、候选补丁或榜单。

## 本机数据（不是 CI）

第三方数据集不进仓库（`data/` 已在 `.gitignore`）。本仓库不附带下载脚本。CI 不拉取、也不校验下面的文件。

本地测试打开的是 gzip JSONL。CI 不校验这个哈希；文件不在树里时测试跳过，本文也没有在缺少该文件的环境里重算它。

- 路径：`data/swebench_multimodal_dev.jsonl.gz`
- 来源记录：HuggingFace `princeton-nlp/SWE-bench_Multimodal` 的 dev split
- 预期 gzip sha256：`f2290f5119d1100b967507fe86ee0285103988a5a3667d665e245fc123322756`

文件存在时，`tests/test_real_data.py` 会把磁盘字节和上一行哈希比对，并核对 102 行与 R1 独立命中 44。

初始提交还记录过两份中间文件。仓库里没有这两份文件，没有任何测试打开它们，CI 也不校验：

- 源 parquet（1,431,630 B）sha256：`617ebc06a461a9b28b7fed9cc6627ed96e87024a63f3a84ffe13cd63b64c7481`
- 未压缩 JSONL sha256：`ee2b38a50ea85890a7f01206a9ba83555d5eb90218277c67c74da566680a227f`

有该 gzip 时可以本地构建（输出目录已忽略，不会被提交）：

```bash
python3 -m swe_subset build \
  --input data/swebench_multimodal_dev.jsonl.gz \
  --out out/local-real --label swebench-multimodal-dev
```

## 边界

- 构建器运行时不联网，不下载数据集。
- 不调用 `git apply`，不执行测试补丁。
- 第三方数据集不入库。
- MIT License。
