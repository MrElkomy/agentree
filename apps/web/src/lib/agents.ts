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

export const TOOL_LABEL: Record<string, { title: string; hint: string }> = {
  create_lead: { title: "Capture leads", hint: "Offer visitors a form to leave their contact details." },
  update_lead: { title: "Update leads", hint: "Visitors can correct the details they already sent." },
  create_follow_up_task: {
    title: "Create follow-up reminders",
    hint: "Add a reminder for your team to contact each new lead.",
  },
};

export type Agent = AgentConfig;
