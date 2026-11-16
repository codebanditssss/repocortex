export const scopeEvidence = [
  {
    study: "Django retrospective",
    measure: "Learned vs frozen · strict function Acc@10",
    result: "45.1% → 48.3%",
    delta: "+3.1pp",
    conclusion: "Demonstrated on this split",
    href: "https://github.com/codebanditssss/repocortex/blob/main/results/baselines.json",
  },
  {
    study: "Starlette prospective",
    measure: "Untouched holdout · strict function Acc@10",
    result: "54.2% vs 54.2%",
    delta: "0.0pp · 24 ties",
    conclusion: "No demonstrated advantage",
    href: "https://github.com/codebanditssss/repocortex/blob/main/results/starlette_prequential.md",
  },
  {
    study: "Repair outcomes",
    measure: "Learned vs frozen · independently tested",
    result: "1/2 vs 1/2",
    delta: "Same repair count",
    conclusion: "No demonstrated advantage",
    href: "https://github.com/codebanditssss/repocortex/blob/main/results/learning_repair_followup.md",
  },
] as const;
