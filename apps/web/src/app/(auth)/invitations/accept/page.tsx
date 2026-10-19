import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthFallback } from "@/components/auth";
import { AcceptInvitation } from "./accept-invitation";

export const metadata: Metadata = { title: "Accept invitation" };

export default function AcceptInvitationPage() {
  return (
    <Suspense fallback={<AuthFallback />}>
      <AcceptInvitation />
    </Suspense>
  );
}
