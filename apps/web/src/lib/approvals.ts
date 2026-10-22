/** Approvals (Task 19): labels for actions, statuses and reasons the backend reports. */

export const ACTION_LABEL: Record<string, string> = {
  send_follow_up_email: "send a follow-up email to a lead",
};

export const STATUS_LABEL: Record<string, string> = {
  pending: "Waiting for approval",
  approved: "Approved · sending",
  executing: "Approved · sending",
  executed: "Done",
  rejected: "Rejected",
  expired: "Expired",
  canceled: "Not needed anymore",
  failed: "Failed",
  unknown: "Outcome unknown",
};

/** Why an approved request didn't run, or ran into a problem. */
export const ERROR_LABEL: Record<string, string> = {
  lead_deleted: "The lead was deleted.",
  lead_contacted: "Your team already contacted the lead.",
  lead_changed: "The lead's email address changed.",
  tool_turned_off: "The agent's follow-up emails were turned off.",
  send_failed: "The email server refused the message. Contact the lead yourself.",
  params_changed: "The request changed after it was approved, so the approval no longer counts.",
  error: "Something went wrong. Contact the lead yourself.",
};

/** Why the backend wants a person to review a draft (never sent automatically). */
export const FLAG_LABEL: Record<string, string> = {
  unverified_numbers: "This draft mentions a number (price, date, discount…) that isn't in your knowledge base. Check it before sending.",
  unverified_links: "This draft contains a link that isn't in your knowledge base. Check it before sending.",
};

export const DECISION_LABEL: Record<string, string> = {
  once: "Approved once",
  always: "Approved · always allowed",
  rule: "Sent automatically (always allowed)",
  reject: "Rejected",
};
