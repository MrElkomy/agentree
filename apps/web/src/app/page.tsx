import { redirect } from "next/navigation";

// The dashboard checks the session with the backend and sends visitors to /login if needed.
export default function Home() {
  redirect("/dashboard");
}
