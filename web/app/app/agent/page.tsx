import type { Metadata } from "next";
import Link from "next/link";
import { PlateHeading } from "@/components/dashboard/plate-heading";
import agent from "@/public/data/agent.json";
import provenance from "@/public/data/provenance.json";

export const metadata: Metadata = { title: "Agent" };

export default function Agent() {
  return (
    <div className="manual-page supporting-screen">
      <PlateHeading chapter="agent" title={<>A shorter route<br /><i>through the code.</i></>} placeholder="Placeholder agent comparison"><p>{agent.note} This plate illustrates the two workflows. It is not an agent benchmark or a claim about token savings.</p></PlateHeading>
      <div className="fixture-banner"><span className="sc">Placeholder fixture</span><p>{agent.ticket}</p></div>
      <div className="agent-comparison">
        {(["without", "with"] as const).map((mode) => <section key={mode} aria-labelledby={`agent-${mode}-title`}><div className="section-rule"><h2 id={`agent-${mode}-title`}>{mode === "with" ? <>With <i>RepoCortex</i></> : <>Without <i>RepoCortex</i></>}</h2><span className="sc">Illustrative only</span></div>
          <dl className="agent-fixture-numbers"><div><dt>Tokens</dt><dd>{agent[mode].tokens.toLocaleString("en-US")}</dd></div><div><dt>Turns</dt><dd>{agent[mode].turns}</dd></div><div><dt>Files read</dt><dd>{agent[mode].files_read}</dd></div></dl>
          {mode === "without" ? <div className="agent-workflow"><p className="sc">The investigation</p><ol><li>Search the repository for the reported symptom.</li><li>Read candidate files and follow their callers.</li><li>Choose where to make the first edit.</li></ol><p className="figure-note">Workflow sketch. A measured execution trace has not been captured.</p></div> : <div className="agent-tool-calls">{agent.with.tool_calls.map((call) => <details key={call.name} open><summary>{call.name} <span className="sc">Fixture payload</span></summary><pre>{JSON.stringify(call.args, null, 2)}</pre><p className="manual-prose">{call.result_summary}</p></details>)}</div>}
        </section>)}
      </div>
      <aside className="measured-aside"><span className="sc">What is measured</span><p>The held-out provenance contains <span className="num">{provenance.hits_with_fixed_in}</span> hits with FIXED_IN evidence and <span className="num">{provenance.hits_with_shortcut}</span> with SHORTCUT evidence. These counts can overlap. They do not measure agent efficiency.</p><Link href="/app/locate">Inspect a real receipt →</Link></aside>
    </div>
  );
}
