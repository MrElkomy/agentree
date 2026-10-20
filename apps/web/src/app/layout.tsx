import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";
import "./globals.css";

// The font file is committed (Inter, latin subset, variable weight; SIL OFL, see
// fonts/LICENSE-inter.txt), so builds never download from Google Fonts and the browser never
// calls Google either.
const inter = localFont({
  src: "./fonts/inter-latin-wght-normal.woff2",
  weight: "100 900",
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "Agentree", template: "%s · Agentree" },
  description:
    "Deploy specialized AI agents for sales, customer service, support, and business operations — all working together in one platform.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#101b2b",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-dvh antialiased">{children}</body>
    </html>
  );
}
