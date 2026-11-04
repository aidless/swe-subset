"""共享测试数据：一条完全合规的合成实例 + 固定路径。"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC = ROOT / "tests" / "fixtures" / "synthetic_instances.jsonl"
REAL_DATA = ROOT / "data" / "swebench_multimodal_dev.jsonl.gz"

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


@pytest.fixture
def valid_record():
    return {
        "instance_id": "demo__demo-1",
        "repo": "demo/demo",
        "base_commit": "0" * 40,
        "patch": PATCH_JS,
        "test_patch": TEST_JS,
        "FAIL_TO_PASS": ["Sum suite adds two numbers correctly"],
        "PASS_TO_PASS": ["Sum suite rejects non numeric input"],
    }
