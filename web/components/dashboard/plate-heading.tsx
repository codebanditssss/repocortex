import { chapters, type ChapterSlug } from "@/lib/chapters";

export function PlateHeading({ chapter, title, children, placeholder }: {
  chapter: ChapterSlug;
  title: React.ReactNode;
  children?: React.ReactNode;
  placeholder?: string;
}) {
  const plate = chapters.find((entry) => entry.slug === chapter)!;
  return (
    <header className="manual-heading">
      <div className="manual-kicker"><span className="sc">Plate {plate.roman}</span><span className="sc">{placeholder || "A field manual for one repository"}</span></div>
      <h1>{title}</h1>
      {children && <div className="manual-dek">{children}</div>}
    </header>
  );
}
