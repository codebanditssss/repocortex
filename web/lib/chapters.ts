export const chapters = [
  { slug: "overview", roman: "i", label: "Overview", href: "/app/overview" },
  { slug: "replay", roman: "ii", label: "Replay", href: "/app/replay" },
  { slug: "locate", roman: "iii", label: "Locate", href: "/app/locate" },
  { slug: "agent", roman: "iv", label: "Agent", href: "/app/agent" },
  { slug: "load", roman: "v", label: "Load", href: "/app/load" },
  { slug: "graph", roman: "vi", label: "Graph", href: "/app/graph" },
  { slug: "connect", roman: "vii", label: "Connect", href: "/app/connect" },
] as const;

export type ChapterSlug = (typeof chapters)[number]["slug"];

export function chapterForPath(pathname: string) {
  return chapters.find((chapter) => pathname === chapter.href) ?? chapters[0];
}
