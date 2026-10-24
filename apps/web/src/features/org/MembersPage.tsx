import { useState } from "react";

import { api } from "@/api/client";
import { errorMessage, fieldErrors, keys, useInvalidatingMutation } from "@/api/hooks";
import type { Invitation, Member } from "@/api/types";
import { useSession } from "@/auth/session";
import {
  Alert,
  Badge,
  Button,
  Card,
  Dialog,
  Field,
  Input,
  Select,
  Spinner,
  Table,
  Td,
  Th,
} from "@/components/ui";
import { useToast } from "@/components/ui/toast";
import { useQuery } from "@tanstack/react-query";

const ROLES = ["owner", "admin", "manager", "collector", "viewer"] as const;

export function MembersPage() {
  const { orgId, membership, me } = useSession();
  const id = orgId ?? "";
  const canAdmin = membership?.role === "owner" || membership?.role === "admin";
  const members = useQuery({
    queryKey: keys.members(id),
    queryFn: () => api.get("/api/v1/orgs/{org_id}/members", { path: { org_id: id } }),
    enabled: !!orgId && membership?.role !== "collector" && membership?.role !== "viewer",
  });
  const invitations = useQuery({
    queryKey: keys.invitations(id),
    queryFn: () => api.get("/api/v1/orgs/{org_id}/invitations", { path: { org_id: id } }),
    enabled: !!orgId && canAdmin,
  });
  if (membership?.role === "collector" || membership?.role === "viewer") {
    return <Alert tone="info">Only managers and above can see the member list.</Alert>;
  }
  if (members.isPending) return <Spinner />;
  if (members.isError) return <Alert>{errorMessage(members.error)}</Alert>;
  return (
    <div className="space-y-6">
      <Card title="Members" actions={canAdmin && <InviteButton orgId={id} />}>
        <Table
          head={
            <>
              <Th>Name</Th>
              <Th>Contact</Th>
              <Th>Role</Th>
              <Th>Joined</Th>
              <Th />
            </>
          }
        >
          {members.data.map((m) => (
            <MemberRow
              key={m.user_id}
              member={m}
              orgId={id}
              canAdmin={canAdmin}
              self={m.user_id === me?.user.id}
            />
          ))}
        </Table>
      </Card>
      {canAdmin && invitations.data && invitations.data.length > 0 && (
        <Card title="Pending invitations">
          <Table
            head={
              <>
                <Th>Sent to</Th>
                <Th>Role</Th>
                <Th>Expires</Th>
                <Th />
              </>
            }
          >
            {invitations.data.map((inv) => (
              <InvitationRow key={inv.id} invitation={inv} orgId={id} />
            ))}
          </Table>
        </Card>
      )}
    </div>
  );
}

function MemberRow({
  member,
  orgId,
  canAdmin,
  self,
}: {
  member: Member;
  orgId: string;
  canAdmin: boolean;
  self: boolean;
}) {
  const toast = useToast();
  const update = useInvalidatingMutation(
    (role: string) =>
      api.patch("/api/v1/orgs/{org_id}/members/{user_id}", {
        path: { org_id: orgId, user_id: member.user_id },
        body: { role },
      }),
    [keys.members(orgId)],
    { onError: (e) => toast.push(errorMessage(e), "error") },
  );
  const remove = useInvalidatingMutation(
    () =>
      api.delete("/api/v1/orgs/{org_id}/members/{user_id}", {
        path: { org_id: orgId, user_id: member.user_id },
      }),
    [keys.members(orgId)],
    { onError: (e) => toast.push(errorMessage(e), "error") },
  );
  return (
    <tr>
      <Td>{member.name || "—"}</Td>
      <Td>
        <div>{member.email}</div>
        <div className="text-neutral-500">{member.phone}</div>
      </Td>
      <Td>
        {canAdmin && !self ? (
          <Select
            value={member.role}
            onChange={(e) => update.mutate(e.target.value)}
            aria-label={`Role of ${member.name || member.email}`}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </Select>
        ) : (
          <Badge tone={member.role === "owner" ? "green" : "neutral"}>{member.role}</Badge>
        )}
      </Td>
      <Td>{new Date(member.joined_at).toLocaleDateString()}</Td>
      <Td>
        {canAdmin && !self && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => confirm("Remove this member?") && remove.mutate(undefined)}
          >
            Remove
          </Button>
        )}
      </Td>
    </tr>
  );
}

function InvitationRow({ invitation, orgId }: { invitation: Invitation; orgId: string }) {
  const revoke = useInvalidatingMutation(
    () =>
      api.delete("/api/v1/orgs/{org_id}/invitations/{invitation_id}", {
        path: { org_id: orgId, invitation_id: invitation.id },
      }),
    [keys.invitations(orgId)],
  );
  return (
    <tr>
      <Td>{invitation.email ?? invitation.phone}</Td>
      <Td>{invitation.role}</Td>
      <Td>{new Date(invitation.expires_at).toLocaleDateString()}</Td>
      <Td>
        <Button variant="ghost" size="sm" onClick={() => revoke.mutate(undefined)}>
          Revoke
        </Button>
      </Td>
    </tr>
  );
}

function InviteButton({ orgId }: { orgId: string }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [destination, setDestination] = useState("");
  const [role, setRole] = useState<string>("collector");
  const invite = useInvalidatingMutation(
    () => {
      const isEmail = destination.includes("@");
      return api.post("/api/v1/orgs/{org_id}/invitations", {
        path: { org_id: orgId },
        body: { email: isEmail ? destination : null, phone: isEmail ? null : destination, role },
      });
    },
    [keys.invitations(orgId)],
    {
      onSuccess: () => {
        toast.push("Invitation sent");
        setOpen(false);
        setDestination("");
      },
    },
  );
  const errs = fieldErrors(invite.error);
  return (
    <>
      <Button onClick={() => setOpen(true)}>Invite member</Button>
      <Dialog open={open} onOpenChange={setOpen} title="Invite a member">
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            invite.mutate(undefined);
          }}
        >
          <Field label="Email or phone number" error={errs.email ?? errs.phone}>
            <Input value={destination} onChange={(e) => setDestination(e.target.value)} required />
          </Field>
          <Field label="Role">
            <Select value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.filter((r) => r !== "owner").map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </Select>
          </Field>
          {invite.isError && !errs.email && !errs.phone && (
            <Alert>{errorMessage(invite.error)}</Alert>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={invite.isPending}>
              Send invitation
            </Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
