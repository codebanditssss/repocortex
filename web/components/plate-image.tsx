import Image from "next/image";
import "./plate-image.css";

export function PlateImage({ src, alt, caption, priority = false, hairline = false, marginalia = false, className = "" }: {
  src: string;
  alt: string;
  caption?: string;
  priority?: boolean;
  hairline?: boolean;
  marginalia?: boolean;
  className?: string;
}) {
  return (
    <figure className={`paper-plate ${hairline ? "paper-plate-framed" : ""} ${marginalia ? "plate-marginalia" : ""} ${className}`}>
      <div className="plate-image-media">
        <Image src={src} alt={alt} width={1024} height={1024} sizes={marginalia ? "300px" : "(max-width: 767px) 260px, 380px"} priority={priority} />
      </div>
      {caption && <figcaption className="sc">{caption}</figcaption>}
    </figure>
  );
}
