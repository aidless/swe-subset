"""规则级测试：每条准入规则的正例、反例，以及定位器的边界。"""

from swe_subset.rules import (
    locate_test,
    rule_f2p_locatable,
    rule_f2p_nonempty,
    rule_no_binary_diff,
    rule_p2p_nonempty,
    rule_repo_local_paths,
    rule_single_language,
    evaluate,
)

PATCH_JS = """diff --git a/src/sum.js b/src/sum.js
index 1111111..2222222 100644
--- a/src/sum.js
+++ b/src/sum.js
@@ -1,3 +1,3 @@
 export function sum(a, b) {
-  return a / b;
+  return a + b;
 }
"""

TEST_JS = """diff --git a/test/sum.test.js b/test/sum.test.js
index 3333333..4444444 100644
--- a/test/sum.test.js
+++ b/test/sum.test.js
@@ -1,4 +1,10 @@
 describe('Sum suite', () => {
+  it('adds two numbers correctly', () => {
+    expect(sum(2, 3)).toBe(5);
+  });
+
   it('rejects non numeric input', () => {
 """

PATCH_PY = """diff --git a/src/alpha.py b/src/alpha.py
index 5555555..6666666 100644
--- a/src/alpha.py
+++ b/src/alpha.py
@@ -1,2 +1,2 @@
 def alpha(x):
-    return x - 1
+    return x + 1
"""

TEST_PY = """diff --git a/tests/test_alpha.py b/tests/test_alpha.py
index 7777777..8888888 100644
--- a/tests/test_alpha.py
+++ b/tests/test_alpha.py
@@ -1,4 +1,8 @@
 from src.alpha import alpha
 
+def test_alpha():
+    assert alpha(1) == 2
+
 def test_beta():
"""


def instance(**overrides):
    record = {
        "instance_id": "demo__demo-1",
        "repo": "demo/demo",
        "base_commit": "0" * 40,
        "patch": PATCH_JS,
        "test_patch": TEST_JS,
        "FAIL_TO_PASS": ["Sum suite adds two numbers correctly"],
        "PASS_TO_PASS": ["Sum suite rejects non numeric input"],
    }
    record.update(overrides)
    return record


def test_r1_pass():
    assert rule_p2p_nonempty(instance()).ok


def test_r1_empty_and_whitespace_only_fail():
    assert not rule_p2p_nonempty(instance(PASS_TO_PASS=[])).ok
    assert not rule_p2p_nonempty(instance(PASS_TO_PASS=[" ", "\t"])).ok


def test_r2_pass_and_fail():
    assert rule_f2p_nonempty(instance()).ok
    assert not rule_f2p_nonempty(instance(FAIL_TO_PASS=[])).ok


def test_r3_title_suffix_pass():
    assert rule_f2p_locatable(instance()).ok


def test_r3_title_too_short_fails_conservatively():
    record = instance(FAIL_TO_PASS=["Sum suite should render"])
    ok, detail = locate_test("Sum suite should render", record["test_patch"])
    assert not ok
    assert "未出现" in detail


def test_r3_nodeid_pass_and_missing_file_fail():
    record = instance(
        patch=PATCH_PY,
        test_patch=TEST_PY,
        FAIL_TO_PASS=["tests/test_alpha.py::test_alpha"],
        PASS_TO_PASS=["tests/test_alpha.py::test_beta"],
    )
    assert rule_f2p_locatable(record).ok
    assert not locate_test("tests/test_other.py::test_alpha", TEST_PY)[0]
    assert not locate_test("tests/test_alpha.py::test_missing", TEST_PY)[0]


def test_r3_fixture_path_with_suite_prefix_and_base_prefix():
    test_patch = """diff --git a/test/fixtures/controller.bar/minBarLength/vertical-pos.js b/test/fixtures/controller.bar/minBarLength/vertical-pos.js
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/test/fixtures/controller.bar/minBarLength/vertical-pos.js
@@ -0,0 +1,3 @@
+module.exports = {
+  config: { type: 'bar' },
+};
"""
    assert locate_test(
        "Chart.controllers.bar auto /base/test/fixtures/controller.bar/minBarLength/vertical-pos.js",
        test_patch,
    )[0]
    # react-pdf 风格：整名就是路径
    assert locate_test("test/fixtures/controller.bar/minBarLength/vertical-pos.js", test_patch)[0]
    assert not locate_test("/base/test/fixtures/missing.js", test_patch)[0]


def test_r3_context_line_counts_as_locatable():
    """wp-calypso-25257：it 标题在上下文行里，不是新增行。"""
    test_patch = """diff --git a/client/state/data-layer/test/index.js b/client/state/data-layer/test/index.js
index aaaaaaa..bbbbbbb 100644
--- a/client/state/data-layer/test/index.js
+++ b/client/state/data-layer/test/index.js
@@ -10,3 +10,3 @@
 describe( 'handlers', () => {
-	describe( '#handleProductCategoriesError()', () => {
+	describe( '#onFetchError()', () => {
 		test( 'should dispatch error', () => {
 """
    assert locate_test("handlers - #onFetchError() - should dispatch error", test_patch)[0]


def test_r3_empty_test_patch_fails():
    assert not rule_f2p_locatable(instance(test_patch="")).ok
    assert not locate_test("anything", "")[0]


def test_r4_single_language_pass():
    assert rule_single_language(instance()).ok


def test_r4_assets_do_not_count_as_language():
    test_patch = TEST_JS + """diff --git a/docs/readme.md b/docs/readme.md
index 9999999..aaaaaaa 100644
--- a/docs/readme.md
+++ b/docs/readme.md
@@ -1 +1 @@
-old
+new
"""
    assert rule_single_language(instance(test_patch=test_patch)).ok


def test_r4_cross_language_fails():
    result = rule_single_language(instance(patch=PATCH_JS + PATCH_PY, test_patch=TEST_JS))
    assert not result.ok
    assert "跨语言" in result.detail


def test_r4_unknown_extension_fails():
    patch = PATCH_JS + """diff --git a/src/weird.xyz b/src/weird.xyz
index 1234567..89abcde 100644
--- a/src/weird.xyz
+++ b/src/weird.xyz
@@ -1 +1 @@
-old
+new
"""
    result = rule_single_language(instance(patch=patch))
    assert not result.ok
    assert "无法归类" in result.detail


def test_r4_assets_only_fails():
    patch = """diff --git a/docs/a.md b/docs/a.md
index 1111111..2222222 100644
--- a/docs/a.md
+++ b/docs/a.md
@@ -1 +1 @@
-old
+new
"""
    assert not rule_single_language(instance(patch=patch, test_patch=patch)).ok


def test_r5_pass():
    assert rule_repo_local_paths(instance()).ok


def test_r5_absolute_path_fails():
    patch = """diff --git a//etc/passwd b//etc/passwd
index 1111111..2222222 100644
--- a//etc/passwd
+++ b//etc/passwd
@@ -1 +1 @@
-old
+new
"""
    result = rule_repo_local_paths(instance(patch=patch))
    assert not result.ok
    assert "绝对路径" in result.detail


def test_r5_parent_traversal_fails():
    patch = """diff --git a/../../outside.txt b/../../outside.txt
index 1111111..2222222 100644
--- a/../../outside.txt
+++ b/../../outside.txt
@@ -1 +1 @@
-old
+new
"""
    result = rule_repo_local_paths(instance(patch=patch))
    assert not result.ok
    assert "越界路径" in result.detail


def test_r5_empty_patches_fail():
    assert not rule_repo_local_paths(instance(patch="")).ok
    assert not rule_repo_local_paths(instance(test_patch="")).ok


def test_r5_unparseable_patch_fails():
    result = rule_repo_local_paths(instance(patch="this is not a diff"))
    assert not result.ok


def test_r6_binary_files_block_fails():
    test_patch = TEST_JS + """diff --git a/test/fixtures/pixel.png b/test/fixtures/pixel.png
index 1111111..2222222 100644
Binary files a/test/fixtures/pixel.png and b/test/fixtures/pixel.png differ
"""
    result = rule_no_binary_diff(instance(test_patch=test_patch))
    assert not result.ok
    assert "pixel.png" in result.detail


def test_r6_git_binary_patch_fails():
    test_patch = TEST_JS + """diff --git a/test/fixtures/logo.png b/test/fixtures/logo.png
new file mode 100644
index 0000000..1111111
GIT binary patch
literal 12
TcmZ?@0000000000
"""
    assert not rule_no_binary_diff(instance(test_patch=test_patch)).ok


def test_r6_clean_patch_passes():
    assert rule_no_binary_diff(instance()).ok


def test_evaluate_records_all_failures_and_primary_order():
    record = instance(
        PASS_TO_PASS=[],
        FAIL_TO_PASS=["Completely unrelated test name"],
        patch=PATCH_JS + PATCH_PY,
    )
    ok, failed, details, primary = evaluate(record)
    assert not ok
    assert failed == ["R1", "R3", "R4"]
    assert primary == "R1"
    assert set(details) == {"R1", "R3", "R4"}
