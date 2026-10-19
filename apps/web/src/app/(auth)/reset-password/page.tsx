import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthFallback } from "@/components/auth";
import { ResetPassword } from "./reset-password";

export const metadata: Metadata = { title: "Reset password" };

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<AuthFallback />}>
      <ResetPassword />
    </Suspense>
  );
}
