import Link from "next/link";
import { Wordmark } from "@/components/brand";
import { buttonClass } from "@/components/button-class";

export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col items-center gap-10 px-4 py-10">
      <Wordmark />
      <div className="flex max-w-md flex-col items-center gap-4 text-center">
        <h1 className="text-2xl font-bold">Page not found</h1>
        <p className="text-ink-muted">The address may be mistyped, or the page has moved.</p>
        <Link href="/dashboard" className={buttonClass("secondary")}>
          Go to your businesses
        </Link>
      </div>
    </div>
  );
}
