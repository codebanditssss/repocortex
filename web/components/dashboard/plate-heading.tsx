import { PlateImage } from "@/components/plate-image";
import { chapters, type ChapterSlug } from "@/lib/chapters";

const descriptions: Record<ChapterSlug, string> = {
  overview: "An ink constellation of graph clusters connected by one vermilion trail.",
  replay: "An ink study of a winding route and the shorter connection learned between its ends.",
  locate: "An ink magnifying glass tracing a route through a small cluster of code connections.",
  agent: "An ink drafting compass points toward a single node in a connected graph.",
  load: "A small ink drawing of parallel requests passing through a shared instrument.",
  graph: "An ink drawing of clustered nodes connected by fine structural lines.",
  connect: "Two small ink graphs joined by a vermilion bridge.",
};

export function SpotArt({ chapter }: { chapter: ChapterSlug }) {
  return <PlateImage className="dashboard-spot" src={`/art/spot-${chapter}.webp`} alt={descriptions[chapter]} caption={`Fig. 0 / ${chapter} study`} hairline />;
}

export function PlateHeading({ chapter, title, children, art = true, placeholder }: {
  chapter: ChapterSlug;
  title: React.ReactNode;
  children?: React.ReactNode;
  art?: boolean;
  placeholder?: string;
}) {
  const plate = chapters.find((entry) => entry.slug === chapter)!;
  return (
    <header className={`manual-heading${art ? " with-spot" : ""}`}>
      <div className="manual-kicker"><span className="sc">Plate {plate.roman}</span><span className="sc">{placeholder || "A field manual for one repository"}</span></div>
      <h1>{title}</h1>
      {children && <div className="manual-dek">{children}</div>}
      {art && <SpotArt chapter={chapter} />}
    </header>
  );
}
