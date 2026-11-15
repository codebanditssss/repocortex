import { ImageResponse } from "next/og";

export const alt = "RepoCortex. Find the functions. Learn from the fix. A learning code graph powered by HydraDB.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default function OpenGraphImage() {
  return new ImageResponse(
    <div style={{ display: "flex", flexDirection: "column", width: "100%", height: "100%", background: "#f2eee6", color: "#1c1914", padding: "48px 64px", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 18, paddingBottom: 26, borderBottom: "1px solid #b8b0a1" }}>
        <svg width="54" height="54" viewBox="0 0 64 64">
          <path d="M16 48V16h15c10 0 14 5 14 11 0 7-4 11-14 11H16m15 0 16 10" fill="none" stroke="#1c1914" strokeWidth="3" />
          <circle cx="47" cy="48" r="4" fill="#b9311c" />
        </svg>
        <span style={{ fontSize: 34, fontWeight: 700, letterSpacing: -1 }}>RepoCortex</span>
        <span style={{ marginLeft: "auto", fontSize: 16, letterSpacing: 3 }}>A LEARNING CODE GRAPH</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", marginTop: 54, fontSize: 78, fontWeight: 700, letterSpacing: -4, lineHeight: 1.12 }}>
        <span>Find the functions.</span>
        <span style={{ color: "#b9311c" }}>Learn from the fix.</span>
      </div>
      <p style={{ fontSize: 25, marginTop: 25, maxWidth: 820, lineHeight: 1.4 }}>
        Your code. Its history. Evidence for the next bug.
      </p>
      <div style={{ display: "flex", alignItems: "center", marginTop: "auto", paddingTop: 24, borderTop: "1px solid #b8b0a1", fontSize: 17 }}>
        <span style={{ letterSpacing: 2 }}>REPORT → FUNCTIONS → EVIDENCE</span>
        <span style={{ marginLeft: "auto", color: "#645d52" }}>Powered by HydraDB</span>
      </div>
    </div>,
    size,
  );
}
