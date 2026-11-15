import type { MetadataRoute } from "next";

export default function sitemap(): MetadataRoute.Sitemap {
  return ["/", "/app/locate", "/app/replay", "/app/agent", "/app/connect"].map((path) => ({
    url: `https://repocortex.vercel.app${path}`,
  }));
}
