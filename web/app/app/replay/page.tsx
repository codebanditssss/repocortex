import type { Metadata } from "next";
import { ReplayScreen } from "@/components/dashboard/replay-screen";
import evaluationJson from "@/public/data/curve.json";
import type { CurveData } from "@/lib/data";

export const metadata: Metadata = { title: "Replay" };

export default function Replay() {
  return <ReplayScreen data={evaluationJson as CurveData} />;
}
