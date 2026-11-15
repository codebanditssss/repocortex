import { isBackendStatus } from "@/lib/live";

export async function GET() {
  try {
    const upstream = await fetch(`${process.env.REPOCORTEX_API_URL || "http://127.0.0.1:8765"}/health`, { cache: "no-store", signal: AbortSignal.timeout(5000) });
    const result: unknown = await upstream.json();
    if (!upstream.ok || !isBackendStatus(result)) throw new Error("Unavailable");
    return Response.json(result, { headers: { "Cache-Control": "no-store" } });
  } catch {
    return Response.json({ mode: "unavailable", connected: false, detail: "The locate service is unavailable." }, { status: 503 });
  }
}
