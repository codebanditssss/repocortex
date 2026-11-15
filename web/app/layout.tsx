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
  metadataBase: new URL("https://repocortex.vercel.app"),
  applicationName: "RepoCortex",
  title: {
    default: "RepoCortex | Find the functions. Learn from the fix.",
    template: "%s | RepoCortex",
  },
  description:
    "Find candidate functions for a bug report with a learning code graph. Inspect evidence from code relationships and past fixes in RepoCortex.",
  icons: {
    icon: "/icon.svg",
    apple: { url: "/apple-icon", sizes: "180x180", type: "image/png" },
  },
  openGraph: {
    type: "website",
    siteName: "RepoCortex",
    locale: "en_US",
    title: "RepoCortex | Find the functions. Learn from the fix.",
    description:
      "Find candidate functions for a bug report. Follow code relationships and past fixes, with evidence behind every result.",
  },
  twitter: {
    card: "summary_large_image",
    title: "RepoCortex | Find the functions. Learn from the fix.",
    description:
      "Find candidate functions for a bug report. Follow code relationships and past fixes, with evidence behind every result.",
    images: [{
      url: "/opengraph-image",
      width: 1200,
      height: 630,
      alt: "RepoCortex. Find the functions. Learn from the fix. A learning code graph powered by HydraDB.",
    }],
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
