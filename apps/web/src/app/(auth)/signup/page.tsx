import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthFallback } from "@/components/auth";
import { SignupForm } from "./signup-form";

export const metadata: Metadata = { title: "Create account" };

export default function SignupPage() {
  return (
    <Suspense fallback={<AuthFallback />}>
      <SignupForm />
    </Suspense>
  );
}
