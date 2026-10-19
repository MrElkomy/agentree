"use client";

import { useParams } from "next/navigation";
import { BusinessShell } from "@/components/business-shell";

export default function BusinessLayout({ children }: { children: React.ReactNode }) {
  const { businessId } = useParams<{ businessId: string }>();
  return (
    <BusinessShell key={businessId} businessId={businessId}>
      {children}
    </BusinessShell>
  );
}
