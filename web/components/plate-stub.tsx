import { chapters, type ChapterSlug } from "@/lib/chapters";

export function PlateStub({
  chapter,
  title,
  description,
  children,
}: {
  chapter: ChapterSlug;
  title: React.ReactNode;
  description: string;
  children?: React.ReactNode;
}) {
  const plate = chapters.find((item) => item.slug === chapter)!;

  return (
    <section className="plate-intro" aria-labelledby="page-title">
      <div className="plate-kicker">
        <p className="sc text-ink2">Plate {plate.roman}</p>
        <p className="sc text-ink2">{plate.label} / Working outline</p>
      </div>
      <h1 id="page-title">{title}</h1>
      <p className="dek">{description}</p>
      {children && <div className="plate-content">{children}</div>}
    </section>
  );
}
