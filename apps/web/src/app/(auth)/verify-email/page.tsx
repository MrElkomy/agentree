import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthFallback } from "@/components/auth";
import { VerifyEmail } from "./verify-email";

export const metadata: Metadata = { title: "Verify email" };

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<AuthFallback />}>
      <VerifyEmail />
    </Suspense>
  );
}
