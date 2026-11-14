import type { Metadata } from "next";
import { PlateHeading } from "@/components/dashboard/plate-heading";
import { CopyConfig } from "@/components/dashboard/copy-config";
import evaluation from "@/public/data/curve.json";

export const metadata: Metadata = { title: "Connect" };

export default function Connect() {
  const snippet = JSON.stringify({
    mcpServers: { repocortex: { command: "python", args: ["/absolute/path/to/RepoCortex/scripts/mcp_server.py"] } },
  }, null, 2);
  return (
    <div className="manual-page supporting-screen">
      <PlateHeading chapter="connect" title={<>Give the next agent<br /><i>a memory.</i></>}><p>Attach a local RepoCortex MCP server to your agent. HydraDB holds the repository graph; the agent asks it where to investigate, with provenance attached to each result.</p></PlateHeading>
      <div className="connect-layout"><section aria-labelledby="connect-config-title"><div className="section-rule"><h2 id="connect-config-title">A connection, <i>not an account.</i></h2><span className="sc">Setup example</span></div><CopyConfig snippet={snippet} /><ol className="setup-steps"><li>Use your local backend checkout and its Python environment.</li><li>Configure HydraDB and build the repository graph using the backend&apos;s setup instructions.</li><li>Replace the path above and add this server to an MCP-compatible client. Restart the client to discover the actual tools.</li></ol><p className="figure-note">No published install command is verified here. The snippet is a placeholder configuration, not a one-line installer. Consult the backend README for dependencies, environment variables, and launch options.</p></section>
      <aside><div className="section-rule"><h2>The local pieces</h2><span className="sc">Not probed</span></div><dl className="connection-record"><div><dt>MCP entry point</dt><dd><code>scripts/mcp_server.py</code></dd></div><div><dt>Locate HTTP service</dt><dd><code>scripts/serve_locate.py</code></dd></div><div><dt>Graph store</dt><dd><a href="https://hydradb.com" target="_blank" rel="noreferrer">HydraDB</a></dd></div><div><dt>Current evaluation scope</dt><dd>{evaluation.scope.join(" / ")}</dd></div><div><dt>Connection status</dt><dd>Not checked by this static frontend</dd></div></dl><section className="mcp-contract" aria-labelledby="mcp-contract-title"><h3 id="mcp-contract-title" className="serif">The intended conversation</h3><p><code>repocortex.locate</code><br />Issue text in. Ranked functions and evidence paths out.</p><p className="figure-note">The agent fixture illustrates this tool name. Actual advertised tools and transport must be verified against your running server. This page does not claim a live connection.</p></section></aside></div>
    </div>
  );
}
