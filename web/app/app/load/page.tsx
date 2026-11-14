import type { Metadata } from "next";
import { PlateHeading } from "@/components/dashboard/plate-heading";
import load from "@/public/data/loadtest.json";

export const metadata: Metadata = { title: "Load" };

export default function Load() {
  return (
    <div className="manual-page supporting-screen">
      <PlateHeading chapter="load" title={<>When the requests<br /><i>arrive together.</i></>}><p>One measured local Locust run against <code>{load.endpoint}</code>. {load.users} concurrent users, {load.duration_s} seconds. A small load test, not a concurrency sweep.</p></PlateHeading>
      <dl className="journal-metrics load-metrics"><div><dt>Concurrent users</dt><dd>{load.users}<small>{load.duration_s} second run</small></dd></div><div><dt>Requests served</dt><dd>{load.requests.toLocaleString("en-US")}<small>{load.failures} failures recorded</small></dd></div><div><dt>Median latency, p50</dt><dd>{load.median_ms}<em> ms</em><small>p95: {load.p95_ms} ms</small></dd></div><div><dt>Requests per second</dt><dd>{load.rps}<small>measured throughput</small></dd></div></dl>
      <div className="load-detail-grid">
        <figure className="latency-figure"><figcaption className="section-rule"><h2>Latency, <i>in milliseconds.</i></h2><span className="cap">Same run, three percentiles</span></figcaption><div className="latency-bars">{[["p50", load.median_ms], ["p95", load.p95_ms], ["p99", load.p99_ms]].map(([label, value]) => <div key={label}><span className="num">{label}</span><div className="latency-track"><div className={`latency-bar ${label === "p95" ? "is-p95" : ""}`} style={{ width: `${Number(value) / 60 * 100}%` }} /></div><span className="num">{value} ms</span></div>)}</div><div className="latency-axis num"><span>0</span><span>20</span><span>40</span><span>60 ms</span></div><p className="figure-note">Bars share a zero-based scale. These are percentile summaries, not a latency distribution or a time series.</p></figure>
        <section aria-labelledby="load-record-title"><div className="section-rule"><h2 id="load-record-title">The run record</h2><span className="sc">Measured</span></div><table className="manual-table run-record"><caption className="sr-only">Single measured Locust run</caption><tbody>{[
          ["Tool", load.tool], ["Endpoint", load.endpoint], ["Concurrent users", load.users], ["Duration", `${load.duration_s} s`], ["Requests", load.requests.toLocaleString("en-US")], ["Failures", load.failures], ["p50 / p95 / p99", `${load.median_ms} / ${load.p95_ms} / ${load.p99_ms} ms`], ["Throughput", `${load.rps} requests/s`],
        ].map(([label, value]) => <tr key={label}><th scope="row">{label}</th><td>{value}</td></tr>)}</tbody></table></section>
      </div>
      <p className="manual-endnote">Source: <code>{load.source}</code>. Local run only. No cache comparison, mixed-write run, 10/50/100-user sweep, or truncation measurement is supplied.</p>
    </div>
  );
}
