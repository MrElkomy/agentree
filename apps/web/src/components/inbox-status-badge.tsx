import { INBOX_STATUS_LABEL, INBOX_STATUS_STYLE, type InboxStatus } from "@/lib/inbox";

export function InboxStatusBadge({ status }: { status: InboxStatus }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold whitespace-nowrap ${INBOX_STATUS_STYLE[status]}`}
      data-testid="inbox-status"
    >
      {INBOX_STATUS_LABEL[status]}
    </span>
  );
}
