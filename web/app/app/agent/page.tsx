import type { Metadata } from "next";
import Link from "next/link";
import { PlateHeading } from "@/components/dashboard/plate-heading";
import agent from "@/public/data/agent.json";

export const metadata: Metadata = { title: "Agent" };

const n = (value: number) => value.toLocaleString("en-US");
const share = (value: number) => value.toFixed(2);
const usd = (value: number) => `$${value.toFixed(3)}`;

const arms = [
  { key: "without", title: <>Without <i>RepoCortex</i></>, note: "search, read, repeat" },
  { key: "with", title: <>With <i>RepoCortex</i></>, note: `-${agent.savings.with_input_tokens_pct}% input tokens` },
  { key: "with_locate_first", title: <>Told to call it <i>first</i></>, note: `-${agent.savings.first_input_tokens_pct}% input tokens` },
] as const;

export default function Agent() {
  const rows: [string, string, string, string, string][] = [
    ["Top-1 function correct", share(agent.without.top1_function_hit), share(agent.with.top1_function_hit), share(agent.with_locate_first.top1_function_hit), share(agent.tool_only.top1_function_hit)],
    ["Top-1 file correct", share(agent.without.top1_file_hit), share(agent.with.top1_file_hit), share(agent.with_locate_first.top1_file_hit), share(agent.tool_only.top1_file_hit)],
    ["Input tokens per issue", n(agent.without.tokens), `${n(agent.with.tokens)} (-${agent.savings.with_input_tokens_pct}%)`, `${n(agent.with_locate_first.tokens)} (-${agent.savings.first_input_tokens_pct}%)`, "0"],
    ["Tool calls per issue", String(agent.without.tool_calls_mean), String(agent.with.tool_calls_mean), String(agent.with_locate_first.tool_calls_mean), "1"],
    ["Files opened per issue", String(agent.without.files_read), String(agent.with.files_read), String(agent.with_locate_first.files_read), "0"],
    ["Cost per issue", usd(agent.without.cost_usd_mean), `${usd(agent.with.cost_usd_mean)} (-${agent.savings.with_cost_pct}%)`, `${usd(agent.with_locate_first.cost_usd_mean)} (-${agent.savings.first_cost_pct}%)`, "$0"],
  ];
  return (
    <div className="manual-page supporting-screen">
      <PlateHeading chapter="agent" title={<>A shorter route<br /><i>through the code.</i></>} placeholder={`Measured agent eval / ${agent.n} Django issues`}><p>{agent.note}</p></PlateHeading>
      <div className="fixture-banner"><span className="sc">Measured</span><p>{agent.n} held-out Django issues, model <code>{agent.model}</code>, same checkout and tools in every arm. The ticket number is never shown.</p></div>
      <div className="agent-comparison agent-comparison-three">
        {arms.map((arm) => <section key={arm.key} aria-labelledby={`agent-${arm.key}-title`}><div className="section-rule"><h2 id={`agent-${arm.key}-title`}>{arm.title}</h2><span className="sc">{arm.note}</span></div>
          <dl className="agent-fixture-numbers"><div><dt>Input tokens</dt><dd>{n(agent[arm.key].tokens)}</dd></div><div><dt>Turns</dt><dd>{agent[arm.key].turns}</dd></div><div><dt>Files read</dt><dd>{agent[arm.key].files_read}</dd></div></dl>
        </section>)}
      </div>
      <section className="agent-table" aria-labelledby="agent-table-title">
        <div className="section-rule"><h2 id="agent-table-title">The eval record</h2><span className="sc">Means per issue</span></div>
        <div className="manual-table-scroll" role="region" aria-label="Agent eval results" tabIndex={0}>
          <table className="manual-table">
            <caption>Oldest {agent.n} held-out fixes. The last column is <code>locate_bug</code> alone, with no model.</caption>
            <thead><tr><th scope="col">Metric</th><th scope="col">Without</th><th scope="col">With</th><th scope="col">Call it first</th><th scope="col">locate_bug alone</th></tr></thead>
            <tbody>{rows.map(([label, ...cells]) => <tr key={label}><th scope="row">{label}</th>{cells.map((cell, index) => <td key={index}>{cell}</td>)}</tr>)}</tbody>
          </table>
        </div>
        <p className="figure-note">Accuracy is within noise across arms: one issue out of {agent.n}. <code>locate_bug</code> alone names the right function first {share(agent.tool_only.top1_function_hit)} of the time against {share(agent.without.top1_function_hit)} for the agent searching by itself, in under a second and with no model call.</p>
      </section>
      <section className="agent-example" aria-labelledby="agent-example-title">
        <div className="section-rule"><h2 id="agent-example-title">One run, <i>{agent.ticket}</i></h2><span className="sc">Measured trace</span></div>
        <div className="agent-tool-calls">{agent.with.tool_calls.map((call) => <details key={call.name} open><summary>{call.name}</summary><pre>{JSON.stringify(call.args, null, 2)}</pre><p className="manual-prose">{call.result_summary}</p></details>)}</div>
      </section>
      <aside className="measured-aside"><span className="sc">Source</span><p><code>{agent.source}</code> and <code>{agent.tool_only.source}</code>. Thirty issues, one model, one run each, so small differences are noise.</p><Link href="/app/locate">Inspect a real receipt →</Link></aside>
    </div>
  );
}
