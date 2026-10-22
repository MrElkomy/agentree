import type { AgentConfig } from "./api";

/** Default names of the roles (the backend's registry); a business may set its own. */
export const DEFAULT_TITLES = new Set(["Sales Agent", "Customer Service", "Technical Support", "Data Analyst", "Executive Assistant"]);

/** "Acme Sales Agent" for a default name, else the business's own name for it ("Sara"). */
export function agentLabel(businessName: string, agentName?: string | null): string {
  if (!agentName) return `${businessName} Sales Agent`;
  return DEFAULT_TITLES.has(agentName) ? `${businessName} ${agentName}` : agentName;
}

/** Entry button text on the public page. */
export function chatWith(agentName: string): string {
  return DEFAULT_TITLES.has(agentName) ? `Chat with our ${agentName}` : `Chat with ${agentName}`;
}

export const ENTRY_HINT: Record<string, string> = {
  sales: "Questions about products or prices? Get an answer now.",
  customer_service: "Orders, accounts or a problem? We're here to help.",
  technical_support: "Setup or something not working? Let's fix it.",
};

/** Customer-facing roles, in the order the dashboard lists them. */
export const PUBLIC_ROLES: { role: string; title: string }[] = [
  { role: "sales", title: "Sales Agent" },
  { role: "customer_service", title: "Customer Service" },
  { role: "technical_support", title: "Technical Support" },
];

export const TOOL_LABEL: Record<string, { title: string; hint: string }> = {
  resolve_conversation: {
    title: "Mark conversations resolved",
    hint: "When the customer confirms their issue is solved, the agent closes the conversation.",
  },
  create_lead: { title: "Capture leads", hint: "Offer visitors a form to leave their contact details." },
  update_lead: { title: "Update leads", hint: "Visitors can correct the details they already sent." },
  create_follow_up_task: {
    title: "Create follow-up reminders",
    hint: "Add a reminder for your team to contact each new lead.",
  },
  send_follow_up_email: {
    title: "Draft follow-up emails",
    hint: "If a new lead hasn't been contacted after 24 hours, the agent drafts an email to them. Nothing is sent until an owner or admin approves it (once, or always).",
  },
};

export type Agent = AgentConfig;
