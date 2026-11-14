import type { Metadata } from "next";
import { LocateScreen } from "@/components/dashboard/locate-screen";
import provenance from "@/public/data/provenance.json";
import type { ProvenanceData } from "@/lib/data";

export const metadata: Metadata = { title: "Locate" };

export default function Locate() {
  return <LocateScreen data={provenance as ProvenanceData} />;
}
