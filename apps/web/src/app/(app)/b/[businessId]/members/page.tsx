"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useBusiness } from "@/components/business-shell";
import { Dialog } from "@/components/dialog";
import { useSession } from "@/components/session";
import { Alert, Button, RoleBadge, SelectField, Spinner, TextField } from "@/components/ui";
import { api, type Invitation, type Member, type Role } from "@/lib/api";
import { ROLE_LABEL, atLeast, canManage, grantableRoles } from "@/lib/roles";

type Notice = { tone: "success" | "warning" | "error"; text: string } | null;

export default function MembersPage() {
  const { business } = useBusiness();
  const { handleError } = useSession();
  const isAdmin = atLeast(business.role, "admin");
  const base = `/api/businesses/${encodeURIComponent(business.id)}`;

  const [members, setMembers] = useState<Member[] | null>(null);
  const [invitations, setInvitations] = useState<Invitation[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice>(null);

  const fetchMembers = useCallback(() => api<Member[]>(`${base}/members`), [base]);
  const fetchInvitations = useCallback(
    () => (isAdmin ? api<Invitation[]>(`${base}/invitations`) : Promise.resolve(null)),
    [base, isAdmin],
  );

  const loadMembers = useCallback(async () => {
    try {
      setMembers(await fetchMembers());
    } catch (err) {
      setLoadError(handleError(err));
    }
  }, [fetchMembers, handleError]);

  const loadInvitations = useCallback(async () => {
    try {
      setInvitations(await fetchInvitations());
    } catch (err) {
      setLoadError(handleError(err));
    }
  }, [fetchInvitations, handleError]);

  useEffect(() => {
    let cancelled = false;
    const fail = (err: unknown) => {
      if (!cancelled) setLoadError(handleError(err));
    };
    fetchMembers().then((m) => !cancelled && setMembers(m), fail);
    fetchInvitations().then((i) => !cancelled && setInvitations(i), fail);
    return () => {
      cancelled = true;
    };
  }, [fetchMembers, fetchInvitations, handleError]);

  return (
    <div className="flex max-w-4xl flex-col gap-10">
      <title>{`Members · ${business.name} · Agentree`}</title>
      <header className="flex flex-col gap-2">
        <h1 className="text-2xl font-bold sm:text-3xl">Members</h1>
        <p className="max-w-prose text-ink-muted">
          {isAdmin
            ? "Everyone who can work in this business. Owners manage everyone; admins manage members."
            : "Everyone who can work in this business. Ask an owner or admin to change roles or invite people."}
        </p>
      </header>

      {notice ? <Alert tone={notice.tone}>{notice.text}</Alert> : null}
      {loadError ? <Alert tone="error">{loadError}</Alert> : null}

      <section aria-labelledby="members-heading" className="flex flex-col gap-4">
        <h2 id="members-heading" className="text-lg font-semibold">
          Team
          {members ? <span className="ml-2 text-base font-normal text-ink-muted">({members.length})</span> : null}
        </h2>
        {members ? (
          <MembersTable
            members={members}
            base={base}
            onChanged={loadMembers}
            onNotice={setNotice}
          />
        ) : loadError ? null : (
          <Spinner label="Loading members…" />
        )}
      </section>

      {isAdmin ? (
        <>
          <section
            aria-labelledby="invite-heading"
            className="rounded-lg border border-line bg-surface p-6"
          >
            <h2 id="invite-heading" className="text-lg font-semibold">
              Invite someone
            </h2>
            <p className="mt-1 mb-5 text-sm text-ink-muted">
              They&apos;ll get an email with a link that works for 7 days.
            </p>
            <InviteForm
              base={base}
              actorRole={business.role}
              onInvited={(text, tone) => {
                setNotice({ tone, text });
                void loadInvitations();
              }}
            />
          </section>
          <section aria-labelledby="pending-heading" className="flex flex-col gap-4">
            <h2 id="pending-heading" className="text-lg font-semibold">
              Pending invitations
            </h2>
            {invitations ? (
              <InvitationList
                invitations={invitations}
                base={base}
                onChanged={loadInvitations}
                onNotice={setNotice}
              />
            ) : (
              <Spinner label="Loading invitations…" />
            )}
          </section>
        </>
      ) : null}
    </div>
  );
}

function MembersTable({
  members,
  base,
  onChanged,
  onNotice,
}: {
  members: Member[];
  base: string;
  onChanged: () => Promise<void>;
  onNotice: (n: Notice) => void;
}) {
  const router = useRouter();
  const { me, handleError, refreshBusinesses } = useSession();
  const { business, reload } = useBusiness();
  const myRole = business.role;
  const [pending, setPending] = useState<string | null>(null);
  const [removing, setRemoving] = useState<Member | null>(null);

  async function changeRole(m: Member, role: Role) {
    if (role === m.role) return;
    setPending(m.user_id);
    onNotice(null);
    try {
      await api<Member>(`${base}/members/${encodeURIComponent(m.user_id)}`, "PATCH", { role });
      onNotice({ tone: "success", text: `${m.email} is now ${ROLE_LABEL[role].toLowerCase()}.` });
      await onChanged();
      if (m.user_id === me.id) {
        await reload();
        await refreshBusinesses();
      }
    } catch (err) {
      onNotice({ tone: "error", text: handleError(err) });
      await onChanged();
    } finally {
      setPending(null);
    }
  }

  async function remove(m: Member) {
    setPending(m.user_id);
    onNotice(null);
    try {
      await api(`${base}/members/${encodeURIComponent(m.user_id)}`, "DELETE");
      setRemoving(null);
      if (m.user_id === me.id) {
        await refreshBusinesses();
        router.push("/dashboard");
        return;
      }
      onNotice({ tone: "success", text: `${m.email} was removed from ${business.name}.` });
      await onChanged();
    } catch (err) {
      setRemoving(null);
      onNotice({ tone: "error", text: handleError(err) });
    } finally {
      setPending(null);
    }
  }

  const options = grantableRoles(myRole);
  const ownerCount = members.filter((m) => m.role === "owner").length;
  const isSelf = removing?.user_id === me.id;

  return (
    <>
      <div
        role="region"
        aria-label="Members"
        tabIndex={0}
        className="relative overflow-x-auto rounded-lg border border-line bg-surface"
      >
        <table className="w-full text-left text-sm">
          <thead className="border-b border-line bg-paper text-ink-muted">
            <tr>
              <th scope="col" className="px-4 py-3 font-semibold">
                Email
              </th>
              <th scope="col" className="px-4 py-3 font-semibold">
                Role
              </th>
              <th scope="col" className="px-4 py-3 text-right font-semibold">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {members.map((m) => {
              const self = m.user_id === me.id;
              const manageable = canManage(myRole, m.role) && options.length > 0;
              // The sole owner can't leave (the backend refuses with last_owner).
              const canLeave = self && !(m.role === "owner" && ownerCount === 1);
              return (
                <tr key={m.user_id} data-testid="member-row">
                  <td className="px-4 py-3">
                    <span className="break-all">{m.email}</span>
                    {self ? <span className="ml-2 text-ink-muted">(you)</span> : null}
                  </td>
                  <td className="px-4 py-3">
                    {manageable ? (
                      <SelectField
                        label={`Role for ${m.email}`}
                        hideLabel
                        value={m.role}
                        disabled={pending === m.user_id}
                        onChange={(e) => void changeRole(m, e.target.value as Role)}
                        className="w-32"
                      >
                        {/* Keep the current role selectable even if the actor can't grant it. */}
                        {[...new Set<Role>([m.role, ...options])].map((r) => (
                          <option key={r} value={r}>
                            {ROLE_LABEL[r]}
                          </option>
                        ))}
                      </SelectField>
                    ) : (
                      <RoleBadge role={m.role} />
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {canLeave || (!self && canManage(myRole, m.role)) ? (
                      <Button
                        variant={self ? "ghost" : "danger"}
                        size="sm"
                        disabled={pending === m.user_id}
                        onClick={() => setRemoving(m)}
                      >
                        {self ? "Leave" : "Remove"}
                        <span className="sr-only"> {m.email}</span>
                      </Button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <Dialog
        open={removing !== null}
        onClose={() => setRemoving(null)}
        title={isSelf ? `Leave ${business.name}?` : "Remove this member?"}
        description={
          isSelf
            ? "You'll lose access to this business until someone invites you again."
            : `${removing?.email ?? ""} will lose access to ${business.name} right away.`
        }
      >
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="ghost" onClick={() => setRemoving(null)}>
            Cancel
          </Button>
          <Button
            variant="danger"
            busy={pending !== null}
            onClick={() => removing && void remove(removing)}
          >
            {isSelf ? "Leave business" : "Remove member"}
          </Button>
        </div>
      </Dialog>
    </>
  );
}

function InviteForm({
  base,
  actorRole,
  onInvited,
}: {
  base: string;
  actorRole: Role;
  onInvited: (text: string, tone: "success" | "warning") => void;
}) {
  const { handleError } = useSession();
  const options = grantableRoles(actorRole);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const inv = await api<Invitation>(`${base}/invitations`, "POST", { email, role });
      if (inv.email_sent === false) {
        onInvited(
          `Invitation for ${inv.email} was saved, but the email failed to send. Invite them again to resend it.`,
          "warning",
        );
      } else {
        onInvited(`Invitation sent to ${inv.email}.`, "success");
      }
      setEmail("");
      setRole("member");
    } catch (err) {
      setError(handleError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4" aria-label="Invite someone">
      {error ? <Alert tone="error">{error}</Alert> : null}
      <div className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_10rem_auto] sm:items-end">
        <TextField
          label="Email"
          type="email"
          name="invite-email"
          autoComplete="off"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <SelectField label="Role" value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {options.map((r) => (
            <option key={r} value={r}>
              {ROLE_LABEL[r]}
            </option>
          ))}
        </SelectField>
        <Button type="submit" busy={busy}>
          Send invitation
        </Button>
      </div>
    </form>
  );
}

const dateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });

function InvitationList({
  invitations,
  base,
  onChanged,
  onNotice,
}: {
  invitations: Invitation[];
  base: string;
  onChanged: () => Promise<void>;
  onNotice: (n: Notice) => void;
}) {
  const { handleError } = useSession();
  const [pending, setPending] = useState<string | null>(null);

  async function revoke(inv: Invitation) {
    setPending(inv.id);
    onNotice(null);
    try {
      await api(`${base}/invitations/${encodeURIComponent(inv.id)}`, "DELETE");
      onNotice({ tone: "success", text: `Invitation for ${inv.email} was revoked.` });
      await onChanged();
    } catch (err) {
      onNotice({ tone: "error", text: handleError(err) });
    } finally {
      setPending(null);
    }
  }

  if (invitations.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-line-strong px-5 py-6 text-sm text-ink-muted">
        No pending invitations. Invite someone above and they&apos;ll show here until they join.
      </p>
    );
  }

  return (
    <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
      {invitations.map((inv) => (
        <li
          key={inv.id}
          data-testid="invitation-row"
          className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
        >
          <span className="flex min-w-0 flex-col">
            <span className="break-all text-sm font-semibold">{inv.email}</span>
            <span className="text-sm text-ink-muted">
              Expires {dateFmt.format(new Date(inv.expires_at))}
            </span>
          </span>
          <span className="flex items-center gap-3">
            <RoleBadge role={inv.role} />
            <Button
              variant="secondary"
              size="sm"
              busy={pending === inv.id}
              onClick={() => void revoke(inv)}
            >
              Revoke<span className="sr-only"> invitation for {inv.email}</span>
            </Button>
          </span>
        </li>
      ))}
    </ul>
  );
}
