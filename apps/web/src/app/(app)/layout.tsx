import { SessionProvider } from "@/components/session";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <SessionProvider>{children}</SessionProvider>;
}
