import type { Metadata } from "next";
import Link from "next/link";
import { CONTACT_EMAIL, LegalPage } from "@/components/legal-page";

export const metadata: Metadata = { title: "Terms" };

export default function TermsPage() {
  return (
    <LegalPage title="Terms">
      <p>
        These terms apply to businesses that create an Agentree account. By creating an account you
        agree to them and to our <Link href="/privacy">privacy notice</Link>.
      </p>

      <h2>Your AI keys and costs</h2>
      <ul>
        <li>
          Agentree uses AI provider accounts that <strong>you</strong> own (&quot;bring your own
          key&quot;). You add a primary key and a backup key.
        </li>
        <li>
          Your provider bills you directly for every AI request made for your business, including
          replies to your visitors. Set a daily reply limit in Agentree and a spending limit with
          your provider.
        </li>
        <li>You are responsible for keeping your provider account in good standing.</li>
      </ul>

      <h2>AI replies</h2>
      <ul>
        <li>
          Replies are written by AI and can be wrong. Agentree tells visitors they are chatting with
          AI. Check your knowledge base, and review what your assistants say.
        </li>
        <li>
          Actions that change things (for example follow-up emails or changes suggested by the
          Executive Assistant) wait for your approval unless you choose to always allow them. You
          are responsible for what you approve.
        </li>
      </ul>

      <h2>Your visitors&apos; data</h2>
      <ul>
        <li>
          You decide how your visitors&apos; conversations and contact details are used, and
          Agentree processes them for you. Tell your visitors how you use their data, and only
          contact people who agreed to it.
        </li>
        <li>
          Raw conversations are deleted after 30 days unless you place one on legal hold.
        </li>
      </ul>

      <h2>Acceptable use</h2>
      <p>
        Do not use Agentree for spam, deception, illegal content, or to collect data you are not
        allowed to collect. Do not try to access other businesses&apos; data or disrupt the
        service. We may suspend an account that does.
      </p>

      <h2>Availability</h2>
      <p>
        We work to keep Agentree running and to fail over to your backup key when your primary
        provider fails, but the service is provided as is, and AI providers can be unavailable.
      </p>

      <h2>Ending your account</h2>
      <p>
        You can stop using Agentree at any time. Ask us to delete your business and its data at{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>

      <h2>Changes</h2>
      <p>We will tell account owners by email before material changes to these terms take effect.</p>
    </LegalPage>
  );
}
