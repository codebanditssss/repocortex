import type { Metadata } from "next";
import { PlateHeading } from "@/components/dashboard/plate-heading";
import { CopyConfig } from "@/components/dashboard/copy-config";
import evaluation from "@/public/data/curve.json";

export const metadata: Metadata = { title: "Connect" };

export default function Connect() {
  const snippet = JSON.stringify({
    mcpServers: { repocortex: { command: "/absolute/path/to/RepoCortex/.venv/bin/python", args: ["/absolute/path/to/RepoCortex/scripts/mcp_server.py"], env: { REPOCORTEX_FEEDBACK_NAMESPACE: "my-team-django" } } },
  }, null, 2);
  const feedbackPrompt = `Use RepoCortex for this confirmed Django fix.

Report: [paste the original bug report]
Unified diff: [paste the reviewed fix diff]

1. Call graph_status. Stop unless mode is live and connected is true.
2. Call locate_bug with the original report and k=10. Keep the ranks and scores.
3. Call learn_from_fix with that same report and the exact confirmed diff. Check that learned is nonempty and persistence is "hydradb feedback journal". If it returns an error or skipped, report it without claiming a new update.
4. Call locate_bug again with the identical report. Show the before/after ranks and scores, including any unchanged results.
5. Stop here. After I restart the local MCP server with the same namespace and base files, run the same search again and compare its results with step 4.

Only learn the reviewed fix I supply. A gain on this same report demonstrates feedback behavior, not held-out accuracy.`;
  return (
    <div className="manual-page supporting-screen">
      <PlateHeading chapter="connect" title={<>Give the next agent<br /><i>a memory.</i></>}><p>Connect your coding agent to local search and confirmed-fix memory in HydraDB.</p></PlateHeading>
      <div className="connect-layout"><section aria-labelledby="connect-config-title"><div className="section-rule"><h2 id="connect-config-title">Connect <i>your agent.</i></h2><span className="sc">Setup example</span></div><CopyConfig snippet={snippet} /><ol className="setup-steps"><li>Set up the backend checkout, Python environment and HydraDB using the <a href="https://github.com/codebanditssss/hydradb-hack#use-it-from-your-agent" target="_blank" rel="noreferrer">README instructions</a>.</li><li>Replace both paths and choose a separate feedback namespace in the configuration above.</li><li>Add this configuration to your MCP client, restart it, then call <code>graph_status</code> to check the connection.</li></ol><p className="figure-note">Local stdio feedback requires <code>REPOCORTEX_FEEDBACK_NAMESPACE</code>. Without it, feedback is rejected. The public website accepts no feedback writes.</p>
        <section id="confirmed-fix" className="mcp-contract" aria-labelledby="feedback-workflow-title">
          <div className="section-rule"><h2 id="feedback-workflow-title">Teach it a <i>confirmed fix.</i></h2><span className="sc">After setup</span></div>
          <p>Use the original bug report and a reviewed unified diff from the indexed Django snapshot. Search first, record the fix, then compare the next search.</p>
          <CopyConfig snippet={feedbackPrompt} title="Prompt for your connected coding agent" buttonLabel="Copy workflow" note="Replace the two bracketed placeholders before sending this to your agent." />
          <details className="receipt-source"><summary>If feedback does not apply</summary><ul className="setup-steps"><li><strong>No matching functions:</strong> check that the diff paths and changed lines belong to the indexed snapshot. An unrelated repository needs its own index.</li><li><strong>Already learned:</strong> the same report and diff are skipped; they do not create a second update.</li><li><strong>Namespace or connection error:</strong> check the MCP environment and HydraDB connection, then restart the local server. Use one writer per namespace.</li></ul></details>
        </section>
      </section>
      <aside><div className="section-rule"><h2>The local pieces</h2><span className="sc">Local setup</span></div><dl className="connection-record"><div><dt>MCP entry point</dt><dd><code>scripts/mcp_server.py</code></dd></div><div><dt>Graph store</dt><dd><a href="https://hydradb.com" target="_blank" rel="noreferrer">HydraDB</a></dd></div><div><dt>Current evaluation scope</dt><dd>{evaluation.scope.join(" / ")}</dd></div></dl><section className="mcp-contract" aria-labelledby="mcp-contract-title"><h3 id="mcp-contract-title" className="serif">The tool contract</h3><p><code>locate_bug(report, k)</code><br />Issue text in. Ranked functions and evidence paths out.</p><p><code>learn_from_fix(report, diff)</code><br />Store a confirmed fix in your durable feedback namespace.</p><p><code>graph_status()</code><br />Check whether search uses live HydraDB or cached evidence.</p><p className="figure-note">Persistence check: after feedback on Django #37442, the confirmed function moved from rank 2 to 1 for that same report and stayed there in a fresh Python process. This is durability evidence, not held-out accuracy or generalization. <a href="https://github.com/codebanditssss/hydradb-hack/blob/main/results/real_feedback_persistence.json" target="_blank" rel="noreferrer">Read the recorded check →</a></p></section></aside></div>
    </div>
  );
}
