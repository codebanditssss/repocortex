import type { Metadata } from "next";
import { PlateHeading } from "@/components/dashboard/plate-heading";
import load from "@/public/data/service-reliability.json";

export const metadata: Metadata = { title: "Load" };

export default function Load() {
  return (
    <div className="manual-page supporting-screen">
      <PlateHeading chapter="load" title={<>When the requests<br /><i>arrive together.</i></>}><p>{load.requests} hosted searches at {load.concurrency} concurrent clients. Every response returned live HydraDB query receipts and passed the response checks.</p></PlateHeading>
      <dl className="journal-metrics load-metrics">
        <div><dt>Concurrent clients</dt><dd>{load.concurrency}<small>120 distinct reports</small></dd></div>
        <div><dt>Valid live responses</dt><dd>{load.valid_live_responses}/{load.requests}<small>HTTP 200 with ranked functions</small></dd></div>
        <div><dt>Median latency, p50</dt><dd>{load.p50_seconds.toFixed(2)}<em> s</em><small>Network and queueing included</small></dd></div>
        <div><dt>95th percentile, p95</dt><dd>{load.p95_seconds.toFixed(2)}<em> s</em><small>Same hosted run</small></dd></div>
      </dl>
      <section aria-labelledby="load-record-title">
        <div className="section-rule"><h2 id="load-record-title">The hosted run</h2><span className="sc">Bounded read-only check</span></div>
        <table className="manual-table run-record"><caption className="sr-only">Hosted search check details</caption><tbody>
          <tr><th scope="row">Endpoint</th><td><code>{load.endpoint}</code></td></tr>
          <tr><th scope="row">Recorded at</th><td><time dateTime={load.checked_at}>{new Date(load.checked_at).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC")}</time></td></tr>
          <tr><th scope="row">Validation</th><td>Live source, ranked hits and database query receipts</td></tr>
        </tbody></table>
        <p className="figure-note">{load.limitations}</p>
      </section>
      <p className="manual-endnote"><a href="https://github.com/codebanditssss/repocortex/blob/main/results/service_reliability_120.json" target="_blank" rel="noreferrer">Read all 120 response records →</a> · <a href="https://github.com/codebanditssss/repocortex/blob/main/results/loadtest.json" target="_blank" rel="noreferrer">Earlier local cached Locust run</a></p>
    </div>
  );
}
