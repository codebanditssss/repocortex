import unittest

from repocortex.serve.learn import functions_from_diff


def node(start, end):
    return {"label": "Function", "file": "q.py", "start": start, "end": end}


class ChangedLineMappingTest(unittest.TestCase):
    def test_huge_claimed_hunk_length_does_not_expand_or_label_other_lines(self):
        diff = "+++ b/q.py\n@@ -1 +1,999999999 @@\n+pass\n"
        self.assertEqual(functions_from_diff(diff, {"actual": node(1, 1), "untouched": node(2, 999999999)}), ["actual"])

    def test_context_does_not_label_adjacent_unchanged_function(self):
        nodes = {"changed": node(45, 50), "unchanged": node(52, 58)}
        diff = "+++ b/q.py\n@@ -46,7 +46,7 @@\n context\n context\n context\n-old\n+fixed\n context\n \n def unchanged():\n"
        self.assertEqual(functions_from_diff(diff, nodes), ["changed"])

    def test_deletion_uses_new_coordinates_not_old_offsets(self):
        nodes = {"changed": node(10, 20), "wrong_old_span": node(100, 110)}
        diff = "+++ b/q.py\n@@ -101,3 +11,2 @@\n context\n-removed\n context\n"
        self.assertEqual(functions_from_diff(diff, nodes), ["changed"])

    def test_whole_function_deletion_does_not_label_next_function(self):
        diff = "+++ b/q.py\n@@ -10,4 +10,1 @@\n-def removed():\n-    body\n-\n def survives():\n"
        self.assertEqual(functions_from_diff(diff, {"survives": node(10, 15)}), [])

    def test_replacement_does_not_label_preceding_function(self):
        diff = "+++ b/q.py\n@@ -10,1 +10,1 @@\n-old\n+new\n"
        self.assertEqual(functions_from_diff(diff, {"before": node(1, 9), "changed": node(10, 15)}), ["changed"])

    def test_plain_unified_diff_separates_files_without_git_headers(self):
        diff = "--- a/q.py\n+++ b/q.py\n@@ -10 +10 @@\n-old\n+new\n--- a/other.py\n+++ b/other.py\n@@ -30 +30 @@\n-old\n+new\n"
        self.assertEqual(functions_from_diff(diff, {"a": node(10, 15), "b": node(30, 35)}), ["a"])

    def test_separate_hunks_and_files_keep_their_own_coordinates(self):
        diff = "diff --git a/q.py b/q.py\n+++ b/q.py\n@@ -10 +10 @@\n-old\n+new\n@@ -30 +30 @@\n-other\n+newer\ndiff --git a/unrelated.py b/unrelated.py\n+++ b/unrelated.py\n@@ -50 +50 @@\n-old\n+new\n"
        self.assertEqual(set(functions_from_diff(diff, {"a": node(10, 15), "b": node(30, 35), "c": node(50, 55)})), {"a", "b"})


if __name__ == "__main__":
    unittest.main()
