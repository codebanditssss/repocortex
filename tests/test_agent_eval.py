import unittest

from scripts.agent_eval import parse_functions, resolve_name, score_predictions


class AgentEvalTest(unittest.TestCase):
    def test_score_maps_a_qualname(self):
        nodes = {
            "func:q.py:QuerySet.filter": {
                "label": "Function",
                "file": "q.py",
                "qualname": "QuerySet.filter",
                "name": "filter",
            }
        }
        self.assertEqual(parse_functions('{"functions": ["QuerySet.filter"]}'), ["QuerySet.filter"])
        tasks = [{"ticket": 1, "gold_functions": ["func:q.py:QuerySet.filter"], "gold_files": ["q.py"]}]
        predictions = [{"ticket": 1, "functions": ["QuerySet.filter"]}]
        summary = score_predictions(tasks, predictions, nodes)
        self.assertEqual(summary["function_acc@10"], 1.0)
        self.assertEqual(resolve_name("missing", {"uid": {}, "qual": {}, "file_name": {}, "name": {}}), "")


if __name__ == "__main__":
    unittest.main()
