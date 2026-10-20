import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// Font files are committed (latin subset, variable weight; SIL OFL, see fonts/LICENSE-*), so
// builds never download from Google Fonts and the browser never calls Google either.
const publicSans = localFont({
  src: "./fonts/public-sans-latin-wght.woff2",
  weight: "100 900",
  variable: "--font-public-sans",
  display: "swap",
});

const bricolage = localFont({
  src: "./fonts/bricolage-grotesque-latin-wght.woff2",
  weight: "200 800",
  variable: "--font-bricolage",
  display: "swap",
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
