import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { cache } from "react";
import { fetchPublicPage } from "@/lib/public-api";
import { WidgetChat } from "./widget-chat";

// The website widget's iframe content (TD-17), loaded by /widget.js. Which websites may
// frame this page is decided by src/proxy.ts (CSP frame-ancestors), not here.

type Props = { params: Promise<{ slug: string }> };

const loadPage = cache(fetchPublicPage);

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const page = await loadPage((await params).slug);
  return {
    title: { absolute: page ? `Chat · ${page.display_name}` : "Chat" },
    robots: { index: false, follow: false },
  };
}

export default async function WidgetPage({ params }: Props) {
  const page = await loadPage((await params).slug);
  if (!page || !page.chat_enabled) notFound();
  return (
    <WidgetChat
      slug={page.slug}
      displayName={page.display_name}
      leadCapture={page.lead_capture}
      retentionDays={page.retention_days ?? 30}
      customerMemory={page.customer_memory ?? true}
    />
  );
}
