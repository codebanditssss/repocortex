# Try RepoCortex on a real investigation

This pilot is for a maintainer of a Python repository who already uses a coding
agent. The question is whether a ranked set of functions and remembered fixes
helps that maintainer investigate bugs. It is not a sales claim or a completed
customer study.

## Choose the trial before seeing results

Use one repository and one source snapshot. Start with five reports for a
usability trial, selected by the maintainer before searching. Include a familiar
bug, an unfamiliar bug, and a report that may fall outside the index. Do not
select only examples that RepoCortex already answers well.

Five reports can expose workflow problems; they cannot establish an accuracy or
cost advantage. For a comparative study, reserve a larger chronological set,
group repeated issue IDs, and agree on the sample size and acceptance criteria
before running either arm. Keep tuning examples separate.

The published runtime covers one Django snapshot. An arbitrary repository needs
its own index and history. Do not paste a report from another repository into the
Django demo and treat the result as a supported investigation.

## First trial

1. Follow [local setup](local-setup.md). Record total setup time and any help
   needed, including failed attempts. The public website can demonstrate Django
   search, but it does not accept private repository uploads or feedback writes.
2. Search the original report. Record whether a useful function appears in the
   first ten, and whether the path, line and explanation are useful at the indexed
   snapshot. Keep the original answer even if a second query works better.
3. Investigate with the same agent and budget you normally use. Record elapsed
   time, tool calls, token usage and the resulting patch separately. A plausible
   function name is not a completed fix.
4. Have a maintainer review the diff. Run the agreed regression tests against the
   unmodified base and patched checkout. Record all failures, skipped tests and
   infrastructure errors; a test that already passed on the base does not prove
   that the patch fixed the reported bug.
5. For a confirmed fix that maps to the index, try the local feedback workflow in
   a separate namespace. Restart and search again. This checks persistence, not
   generalization to unseen bugs.

For a paired agent study, use independent fresh checkouts for the baseline and
assisted arms, the same starting commit/model/tools/budget, and randomize arm
order. Do not carry patches, conversation history or new feedback between arms.
Freeze the retrieval runtime for that study. Feedback behavior is a separate test.

## Feedback to return

Copy this section into a private note. Share only material you have permission to
share; a short redacted summary is enough to identify a workflow problem.

```text
Repository and snapshot (or private description):
Role: maintainer / platform engineer / other
Agent and model:
Setup minutes, including failed attempts:
Where setup needed help:

For each report:
- Report ID:
- Was it selected before seeing the answer?
- Useful function in top 10: yes / no / unknown
- Was the graph explanation helpful? Why?
- Investigation elapsed time:
- Patch produced and reviewed: yes / no
- Base regression test outcome:
- Patched regression test outcome:
- Errors, retries, or missing evidence:

Would you use this on the next bug? Why or why not?
What would it replace in your current workflow?
What stopped you from trusting or using the result?
Who would approve installing this for your team?
Would you trial it on your repository with the setup effort recorded above?
Permission to quote this feedback publicly: no / yes, with attribution as follows
```

Do not turn a positive comment into a paying-customer claim. Record invitations,
completed trials, repeat use, and willingness to pay as separate observations.
No invitations or customer conversations have been conducted by this document.

## Decide whether to continue

The maintainer should define thresholds before the comparative study: acceptable
setup effort, completed-fix quality, investigation time, and acceptable operating
cost. Count the overhead of maintaining the index and reviewing feedback. A
failed trial is useful evidence: retain it and address the actual blocker before
expanding the deployment.
