import { readLimitedBody, BodyTooLargeError, BodyReadTimeoutError } from "@/lib/request-body";
import { isLocateResult } from "@/lib/live";
import { isIP } from "node:net";

function forwardedClientIp(request: Request) {
  return request.headers.get("x-forwarded-for")?.split(",").map((value) => value.trim()).reverse().find((value) => isIP(value) !== 0);
}

export async function POST(request: Request) {
  if (request.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "application/json") {
    return Response.json({ error: "Send JSON with Content-Type: application/json." }, { status: 415 });
  }
  let body;
  try {
    const text = await readLimitedBody(request, 12000 * 12 + 1024);
    if (text.length > 12000 * 12 + 1024) return Response.json({ error: "Keep the report under 12,000 characters." }, { status: 413 });
    body = JSON.parse(text);
  } catch (error) {
    if (error instanceof BodyReadTimeoutError) return Response.json({ error: "Uploading the report timed out. Please try again." }, { status: 408 });
    if (error instanceof BodyTooLargeError) return Response.json({ error: "Keep the report under 12,000 characters." }, { status: 413 });
    return Response.json({ error: "Send a valid bug report." }, { status: 400 });
  }
  if (!body || typeof body.report !== "string" || !body.report.trim() || Array.from(body.report).length > 12000 || (body.k !== undefined && (!Number.isInteger(body.k) || body.k < 1 || body.k > 20))) {
    return Response.json({ error: "Enter a bug report (up to 12,000 characters) and request 1–20 results." }, { status: 400 });
  }
  try {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    const token = process.env.REPOCORTEX_API_TOKEN;
    if (token) {
      headers.Authorization = `Bearer ${token}`;
      const clientIp = forwardedClientIp(request);
      if (clientIp) headers["X-RepoCortex-Client-IP"] = clientIp;
    }
    const upstream = await fetch(`${process.env.REPOCORTEX_API_URL || "http://127.0.0.1:8765"}/locate`, {
      method: "POST", headers, body: JSON.stringify({ report: body.report.trim(), k: body.k ?? 10 }), cache: "no-store", signal: AbortSignal.any([request.signal, AbortSignal.timeout(60000)]),
    });
    if (upstream.status === 413) return Response.json({ error: "The report is too large. Shorten it and try again." }, { status: 413 });
    if (upstream.status === 429) return Response.json({ error: "Too many searches. Please wait briefly and try again." }, { status: 429, headers: { "Retry-After": upstream.headers.get("Retry-After") || "60" } });
    if (upstream.status === 503) return Response.json({ error: "Search is temporarily unavailable. Please try again shortly." }, { status: 503, headers: { "Retry-After": "5" } });
    if (!upstream.ok) return Response.json({ error: "The locate service could not complete this search. Try again." }, { status: 502 });
    const result: unknown = await upstream.json();
    if (!isLocateResult(result)) return Response.json({ error: "The locate service returned an incomplete result." }, { status: 502 });
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch (error) {
    const timedOut = error instanceof Error && (error.name === "TimeoutError" || error.name === "AbortError");
    return Response.json({ error: timedOut ? "The search timed out. Please try again." : "The locate service is unavailable. Saved evidence below is still available." }, { status: timedOut ? 504 : 503 });
  }
}
