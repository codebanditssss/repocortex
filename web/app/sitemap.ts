import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  return [
    "/",
    "/app",
    "/app/overview",
    "/app/locate",
    "/app/replay",
    "/app/agent",
    "/app/connect",
    "/app/graph",
    "/app/load",
  ].map((path) => ({
    url: `https://repocortex.vercel.app${path}`,
  }));
}
