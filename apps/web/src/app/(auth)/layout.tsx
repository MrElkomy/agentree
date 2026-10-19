import { BrandTree, Wordmark } from "@/components/brand";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh grid-rows-[auto_1fr] lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:grid-rows-1">
      <aside className="relative flex flex-col justify-between gap-8 overflow-hidden bg-canopy-deep px-6 py-6 text-white sm:px-10 lg:py-10">
        <Wordmark href="/login" inverted />
        <div className="hidden flex-col gap-10 lg:flex">
          <BrandTree />
          <div className="flex max-w-md flex-col gap-3">
            <p className="font-display text-3xl font-bold leading-tight">
              One workspace for your business and the AI agents that work for it.
            </p>
            <p className="text-base text-white/75">
              Set up your business, bring in your team, and get ready to put agents on support,
              sales and bookings.
            </p>
          </div>
        </div>
        <p className="hidden text-sm text-white/60 lg:block">
          Your data stays in your workspace. Only the people you invite can see it.
        </p>
      </aside>
      <main className="flex items-start justify-center px-4 py-10 sm:px-8 lg:items-center">
        <div className="w-full max-w-md">{children}</div>
      </main>
    </div>
  );
}
