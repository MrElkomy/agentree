import type { Metadata } from "next";
import Link from "next/link";
import { CONTACT_EMAIL, LegalPage } from "@/components/legal-page";

export const metadata: Metadata = { title: "Privacy notice" };

export default function PrivacyPage() {
  return (
    <LegalPage title="Privacy notice">
      <p>
        Agentree gives businesses a team of AI assistants that chat with their website visitors and
        help their staff. This notice explains what we collect, why, and for how long. It covers two
        groups of people: <strong>businesses</strong> that use Agentree (owners and their team) and
        <strong> visitors</strong> who chat with a business&apos;s assistants.
      </p>

      <h2>If you chat with a business&apos;s assistant</h2>
      <ul>
        <li>
          <strong>You are talking to AI.</strong> Replies are written by an AI model. A member of the
          business&apos;s team may read the conversation and reply in person.
        </li>
        <li>
          <strong>Who is responsible.</strong> The business you are chatting with decides how your
          messages and details are used. Agentree processes them on the business&apos;s behalf.
          Questions about your data should go to that business first; you can also contact us.
        </li>
        <li>
          <strong>What is stored.</strong> Your messages, and contact details you choose to share
          (for example your name, email or phone when you ask to be contacted).
        </li>
        <li>
          <strong>AI providers.</strong> To write replies, your messages are sent to the AI provider
          the business chose (for example OpenAI, Anthropic or Google), using the business&apos;s
          own account with that provider.
        </li>
        <li>
          <strong>How long.</strong> Conversations are deleted automatically 30 days after the last
          message, unless the business must keep one for a legal reason. Contact details you gave
          as a lead stay with the business until it deletes them.
        </li>
        <li>
          <strong>Remembering you.</strong> If you confirm your email with a code, the business may
          remember a few useful facts about you for future chats. You can choose &quot;Not
          you?&quot; in the chat to stop this browser from being linked to you.
        </li>
        <li>
          <strong>Emails.</strong> If you leave your email and agree to be contacted, the business
          may send you a follow-up. Every email says why you received it.
        </li>
      </ul>

      <h2>If you use Agentree for your business</h2>
      <ul>
        <li>
          <strong>Account data:</strong> your name, email, password (stored only as a secure hash),
          the businesses you belong to and your role.
        </li>
        <li>
          <strong>Your AI keys:</strong> the API keys you add are encrypted and never shown again in
          full. AI usage is billed to you by your provider; Agentree does not resell AI tokens.
        </li>
        <li>
          <strong>Business content:</strong> your knowledge base, uploaded files, settings, leads and
          conversations. They are kept separate from every other business.
        </li>
        <li>
          <strong>Activity log:</strong> who changed what and when, for security. It never contains
          message content or keys.
        </li>
        <li>
          <strong>Notifications:</strong> emails and, if you turn them on, browser push alerts.
        </li>
      </ul>

      <h2>What we do not do</h2>
      <ul>
        <li>We do not sell personal data or use it for advertising.</li>
        <li>We do not use your conversations to train AI models.</li>
        <li>We do not put tracking or advertising cookies on the chat or the widget.</li>
      </ul>

      <h2>Security and backups</h2>
      <p>
        Data is sent over encrypted connections, each business&apos;s data is isolated in the
        database, and backups are encrypted. Deleted conversations can remain in encrypted backups
        for up to 30 days until those backups expire.
      </p>

      <h2>Your choices</h2>
      <p>
        You can ask for a copy of your data, or for it to be corrected or deleted, by writing to{" "}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. If you chatted with a business,
        we may forward your request to that business, which controls your conversation.
      </p>

      <h2>Changes</h2>
      <p>
        We will update this notice when our practices change and show the date above. See also our{" "}
        <Link href="/terms">terms</Link>.
      </p>
    </LegalPage>
  );
}
