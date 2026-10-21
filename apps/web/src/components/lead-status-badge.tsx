import type { LeadStatus } from "@/lib/api";
import { LEAD_STATUS_LABEL, LEAD_STATUS_STYLE } from "@/lib/leads";

export function LeadStatusBadge({ status }: { status: LeadStatus }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${LEAD_STATUS_STYLE[status]}`}>
      {LEAD_STATUS_LABEL[status]}
    </span>
  );
}
