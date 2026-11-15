import lexical from "@/public/data/lexical_gap.json";
import { formatPercent } from "@/lib/format";

export function EvaluationNote() {
  return (
    <details className="replay-params">
      <summary>What the benchmark measures</summary>
      <p className="news">On {lexical.n} chronological fix rows, function Acc@10 is {formatPercent(lexical.dense_bm25["function_acc@10"])} for dense + BM25 without graph, {formatPercent(lexical.frozen["function_acc@10"])} for the frozen graph, and {formatPercent(lexical.learned["function_acc@10"])} after learning. All gold functions must appear in the top ten.</p>
      <p className="news">This is a retrospective replay on one Django snapshot. Three test rows share tickets with training. Excluding them leaves 316 rows: 42.09%, 45.57%, and 48.73%, respectively. The snapshot includes later fixes; these are offline results, not live request measurements.</p>
      <p className="news"><a href="https://github.com/codebanditssss/hydradb-hack/blob/main/docs/evaluation-audit.md">Read the evaluation audit</a>{" · "}<a href="/data/lexical_gap.json">Download the reproduced comparison</a></p>
    </details>
  );
}
