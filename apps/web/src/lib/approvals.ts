/** Approvals (Task 19): labels for actions, statuses and reasons the backend reports. */

export const ACTION_LABEL: Record<string, string> = {
  send_follow_up_email: "send a follow-up email to a lead",
  set_agent_enabled: "turn an agent on or off",
  update_public_profile: "update the public page",
  update_lead_status: "change a lead's status",
  assign_lead: "assign a lead to a team member",
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
  approver_not_allowed: "Whoever approved it is no longer an owner or admin, so the approval doesn't count.",
  agent_not_available: "That agent isn't available.",
  not_allowed: "The Executive Assistant can't change itself.",
  member_left: "That team member is no longer in the business.",
  error: "Something went wrong. Try again or make the change yourself.",
};

/** Why the backend wants a person to review a draft (never sent automatically). */
export const FLAG_LABEL: Record<string, string> = {
  unverified_numbers: "This draft mentions a number (price, date, discount…) that isn't in your knowledge base. Check it before sending.",
  unverified_links: "This draft contains a link that isn't in your knowledge base. Check it before sending.",
  unverified_recipient:
    "The visitor hasn't confirmed this email address with a code, so it may not be theirs. Check before sending.",
};

export const DECISION_LABEL: Record<string, string> = {
  once: "Approved once",
  always: "Approved · always allowed",
  rule: "Sent automatically (always allowed)",
  reject: "Rejected",
};
