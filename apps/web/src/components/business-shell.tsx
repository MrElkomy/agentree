"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { AccountMenu } from "@/components/account-menu";
import { Wordmark } from "@/components/brand";
import { Popover, menuItemClass } from "@/components/popover";
import { useSession } from "@/components/session";
import { Alert, RoleBadge, Spinner, buttonClass } from "@/components/ui";
import { api, isApiError, type Business } from "@/lib/api";
import { atLeast } from "@/lib/roles";

type BusinessCtx = { business: Business; reload: () => Promise<void> };
const BusinessContext = createContext<BusinessCtx | null>(null);

export function useBusiness(): BusinessCtx {
  const ctx = useContext(BusinessContext);
  if (!ctx) throw new Error("useBusiness outside BusinessShell");
  return ctx;
}

type Load =
  | { state: "loading" }
  | { state: "ready"; business: Business }
  | { state: "missing" }
  | { state: "error"; message: string };

/**
 * The business id in the URL only selects a business; the backend decides access from
 * membership and answers 404 for businesses the user does not belong to.
 */
export function BusinessShell({ businessId, children }: { businessId: string; children: ReactNode }) {
  const { handleError } = useSession();
  const [load, setLoad] = useState<Load>({ state: "loading" });

  const fetchBusiness = useCallback(async (): Promise<Load> => {
    try {
      const business = await api<Business>(`/api/businesses/${encodeURIComponent(businessId)}`);
      return { state: "ready", business };
    } catch (err) {
      if (isApiError(err, 404) || isApiError(err, 422)) return { state: "missing" };
      return { state: "error", message: handleError(err) };
    }
  }, [businessId, handleError]);

  const reload = useCallback(async () => setLoad(await fetchBusiness()), [fetchBusiness]);

  useEffect(() => {
    let cancelled = false;
    void fetchBusiness().then((result) => {
      if (!cancelled) setLoad(result);
    });
    return () => {
      cancelled = true;
    };
  }, [fetchBusiness]);

  let content: ReactNode;
  if (load.state === "loading") {
    content = <Spinner label="Loading business…" />;
  } else if (load.state === "missing") {
    content = (
      <div className="flex max-w-lg flex-col gap-4">
        <h1 className="text-2xl font-bold">Business not available</h1>
        <p className="text-ink-muted">
          This business doesn&apos;t exist, or you&apos;re not a member of it. Ask an owner or admin
          to invite you.
        </p>
        <Link href="/dashboard" className={`${buttonClass("secondary")} w-fit`}>
          Back to your businesses
        </Link>
      </div>
    );
  } else if (load.state === "error") {
    content = <Alert tone="error">{load.message}</Alert>;
  } else {
    content = (
      <BusinessContext.Provider value={{ business: load.business, reload }}>
        {children}
      </BusinessContext.Provider>
    );
  }

  const current = load.state === "ready" ? load.business : null;

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[17rem_minmax(0,1fr)]">
      <Sidebar businessId={businessId} current={current} />
      <main className="px-4 py-8 sm:px-8 lg:px-12 lg:py-10">{content}</main>
    </div>
  );
}

function Sidebar({ businessId, current }: { businessId: string; current: Business | null }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const [lastPath, setLastPath] = useState(pathname);
  if (pathname !== lastPath) {
    // Close the mobile menu after navigating.
    setLastPath(pathname);
    setOpen(false);
  }

  return (
    <div className="border-b border-line bg-surface lg:sticky lg:top-0 lg:flex lg:h-dvh lg:flex-col lg:border-r lg:border-b-0">
      <div className="flex items-center justify-between gap-3 px-4 py-3 lg:px-5 lg:py-5">
        <Wordmark />
        <div className="flex items-center gap-2 lg:hidden">
          <AccountMenu />
          <button
            type="button"
            aria-expanded={open}
            aria-controls="business-nav"
            onClick={() => setOpen((v) => !v)}
            className={buttonClass("secondary", "sm")}
          >
            {open ? "Close" : "Menu"}
          </button>
        </div>
      </div>
      <div
        id="business-nav"
        className={`${open ? "flex" : "hidden"} flex-col gap-6 px-4 pb-5 lg:flex lg:min-h-0 lg:flex-1 lg:px-5`}
      >
        <BusinessSwitcher current={current} />
        {/* On short screens the links scroll; the account stays pinned at the bottom. */}
        <nav aria-label="Business" className="flex flex-col gap-6 lg:min-h-0 lg:flex-1 lg:overflow-y-auto">
          <ul className="flex flex-col gap-0.5">
            <NavItem href={`/b/${businessId}`} label="Overview" />
            <NavItem href={`/b/${businessId}/agents`} label="AI team" />
            <NavItem href={`/b/${businessId}/agents/sales`} label="Test chat" />
            <NavItem href={`/b/${businessId}/inbox`} label="Inbox" section />
            <NavItem href={`/b/${businessId}/leads`} label="Leads" section />
            <NavItem href={`/b/${businessId}/customers`} label="Customers" />
            <NavItem href={`/b/${businessId}/knowledge`} label="Knowledge" />
            <NavItem href={`/b/${businessId}/public-page`} label="Public page & widget" />
            <NavItem href={`/b/${businessId}/ai-providers`} label="AI Providers" />
            <NavItem href={`/b/${businessId}/members`} label="Members" />
            {current && atLeast(current.role, "admin") ? (
              <>
                <NavItem href={`/b/${businessId}/notifications`} label="Notifications" />
                <NavItem href={`/b/${businessId}/activity`} label="Activity log" />
              </>
            ) : null}
          </ul>
        </nav>
        <div className="mt-auto hidden shrink-0 items-center gap-3 border-t border-line pt-4 lg:flex">
          <AccountMenu align="start" side="top" />
          <AccountEmail />
        </div>
      </div>
    </div>
  );
}

function AccountEmail() {
  const { me } = useSession();
  return <span className="min-w-0 truncate text-sm text-ink-muted">{me.email}</span>;
}

function NavItem({ href, label, section = false }: { href: string; label: string; section?: boolean }) {
  const pathname = usePathname();
  // `section`: also active on child pages (e.g. a lead's detail page).
  const active = pathname === href || (section && pathname.startsWith(`${href}/`));
  return (
    <li>
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        className={[
          "flex rounded-md px-3 py-2 text-sm font-semibold",
          active ? "bg-brand-soft text-brand-deep" : "text-ink hover:bg-brand-soft/60",
        ].join(" ")}
      >
        {label}
      </Link>
    </li>
  );
}

function BusinessSwitcher({ current }: { current: Business | null }) {
  const { businesses } = useSession();
  return (
    <Popover
      label={current ? `Switch business, current: ${current.name}` : "Switch business"}
      buttonClassName="flex w-full items-center justify-between gap-3 rounded-lg border border-line-strong bg-paper px-3 py-2.5 text-left hover:border-brand"
      panelClassName="w-full"
      button={
        <>
          <span className="flex min-w-0 flex-col">
            <span className="text-xs text-ink-muted">Business</span>
            <span className="truncate font-semibold" data-testid="current-business">
              {current?.name ?? "…"}
            </span>
          </span>
          <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4 shrink-0 text-ink-muted">
            <path d="M4 6l4-3 4 3M4 10l4 3 4-3" stroke="currentColor" strokeWidth="1.6" fill="none" />
          </svg>
        </>
      }
    >
      {(close) => (
        <div className="flex flex-col">
          <ul aria-label="Your businesses" className="flex max-h-72 flex-col overflow-y-auto">
            {businesses.map((b) => (
              <li key={b.id}>
                <Link
                  href={`/b/${b.id}`}
                  onClick={close}
                  aria-current={current?.id === b.id ? "page" : undefined}
                  className={`${menuItemClass} ${current?.id === b.id ? "bg-brand-soft/60" : ""}`}
                >
                  <span className="truncate">{b.name}</span>
                  <RoleBadge role={b.role} />
                </Link>
              </li>
            ))}
          </ul>
          <div className="mt-1 border-t border-line pt-1">
            <Link href="/dashboard" onClick={close} className={menuItemClass}>
              All businesses and create new
            </Link>
          </div>
        </div>
      )}
    </Popover>
  );
}
