import { FieldShell } from "@/components/field-shell";
import "./dashboard.css";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <FieldShell dashboard>{children}</FieldShell>;
}
