import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Public_Sans } from "next/font/google";
import "./globals.css";

// Self-hosted at build time by next/font: no runtime requests to Google.
const publicSans = Public_Sans({
  subsets: ["latin"],
  variable: "--font-public-sans",
  display: "swap",
});

const bricolage = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-bricolage",
  display: "swap",
  weight: ["600", "700"],
});

export const metadata: Metadata = {
  title: { default: "Agentree", template: "%s · Agentree" },
  description: "An AI workforce for your business.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#1e5a44",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${publicSans.variable} ${bricolage.variable}`}>
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
