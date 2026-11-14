import type { Metadata } from "next";
import {
  Instrument_Serif,
  Inter_Tight,
  Newsreader,
  Reenie_Beanie,
} from "next/font/google";
import localFont from "next/font/local";
import { PaperGrain } from "@/components/paper-grain";
import "./globals.css";

const instrument = Instrument_Serif({
  variable: "--font-instrument",
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  display: "swap",
});

const inter = Inter_Tight({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  weight: ["400", "500"],
  style: ["normal", "italic"],
  display: "swap",
  preload: false,
});

const reenie = Reenie_Beanie({
  variable: "--font-reenie",
  subsets: ["latin"],
  weight: "400",
  display: "swap",
  preload: false,
});

const departure = localFont({
  src: "./fonts/DepartureMono-Regular.woff2",
  variable: "--font-departure",
  display: "swap",
  preload: false,
});

export const metadata: Metadata = {
  title: {
    default: "RepoCortex | A repository field manual",
    template: "%s | RepoCortex",
  },
  description:
    "A learning code graph that follows calls, imports, and past fixes to help find the next bug.",
  icons: { icon: "/icon.svg" },
  openGraph: {
    title: "RepoCortex | A repository field manual",
    description:
      "A learning code graph that follows calls, imports, and past fixes to help find the next bug.",
    images: [
      {
        url: "/art/gh-social-1280x640.webp",
        width: 1280,
        height: 640,
        alt: "RepoCortex: a code graph that learns from every fix. Plus 11.0 points over dense search, function Acc@10, interval 7.5 to 14.4.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "RepoCortex | A repository field manual",
    description:
      "A learning code graph that follows calls, imports, and past fixes to help find the next bug.",
    images: ["/art/x-card-1200x675.webp"],
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${instrument.variable} ${inter.variable} ${newsreader.variable} ${reenie.variable} ${departure.variable}`}
    >
      <body>
        <a className="skip-link" href="#main-content">
          Skip to content
        </a>
        {children}
        <PaperGrain />
      </body>
    </html>
  );
}
