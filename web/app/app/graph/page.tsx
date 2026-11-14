import type { Metadata } from "next";
import { PlateHeading } from "@/components/dashboard/plate-heading";
import { GraphPlate } from "@/components/landing/graph-plate";
import stats from "@/public/data/graph_stats.json";

export const metadata: Metadata = { title: "Graph" };

export default function Graph() {
  return (
    <div className="manual-page supporting-screen">
      <PlateHeading chapter="graph" title={<>The repository,<br /><i>in relation.</i></>}><p>Code entities, concepts, and symptoms in the scoped Django graph. The inventory below is measured. The printed layout is a stand-in, not a map exported from HydraDB.</p></PlateHeading>
      <div className="graph-inventory-layout"><figure className="inventory-plate"><figcaption className="section-rule"><span className="cap"><b>FIG. 1</b> The shape of a connected repository</span><span className="sc">Placeholder layout</span></figcaption><div className="graph-stage"><GraphPlate modules /></div><p className="figure-note">Dithered from the precomputed placeholder in graph.json using the shared print renderer. Node positions, labels, and connections are illustrative. No live graph exploration is connected.</p></figure>
      <section aria-labelledby="inventory-title"><div className="section-rule"><h2 id="inventory-title">The inventory</h2><span className="sc">Real counts</span></div><dl className="inventory-totals"><div><dt>Nodes</dt><dd>{stats.db_nodes.toLocaleString("en-US")}</dd></div><div><dt>Edges</dt><dd>{stats.db_edges.toLocaleString("en-US")}</dd></div></dl><table className="manual-table"><caption>Node labels / captured graph snapshot</caption><thead><tr><th scope="col">Label</th><th scope="col">Count</th></tr></thead><tbody>{Object.entries(stats.labels).map(([label, count]) => <tr key={label}><th scope="row">{label}</th><td>{count.toLocaleString("en-US")}</td></tr>)}</tbody></table><p className="figure-note">Backend: {stats.backend}. Local and database counts agree. No node or edge truncations were recorded.</p></section></div>
      <p className="manual-endnote">Source: <code>{stats.source}</code> / snapshot <code>{stats.snapshot}</code></p>
    </div>
  );
}
