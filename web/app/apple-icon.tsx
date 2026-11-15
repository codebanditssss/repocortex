import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    <div style={{ display: "flex", width: "100%", height: "100%", background: "#f2eee6", alignItems: "center", justifyContent: "center" }}>
      <svg width="156" height="156" viewBox="0 0 64 64">
        <path d="M16 48V16h15c10 0 14 5 14 11 0 7-4 11-14 11H16m15 0 16 10" fill="none" stroke="#1c1914" strokeWidth="3" />
        <circle cx="47" cy="48" r="4" fill="#b9311c" />
      </svg>
    </div>,
    size,
  );
}
