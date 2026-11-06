import { useState } from "react";
import type { Invitation } from "@/api/accounts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function InvitationLink({ invitation }: { invitation: Invitation }) {
  const [message, setMessage] = useState("");
  return <div className="space-y-2 border-t border-border pt-4">
    <Label htmlFor="invitation-link">Invitation for {invitation.username}</Label>
    <div className="flex flex-wrap gap-2"><Input id="invitation-link" readOnly value={invitation.invitation_url} className="min-w-0 flex-1 basis-64" onFocus={event => event.currentTarget.select()} />
      <Button type="button" variant="outline" onClick={async () => {
        try { await navigator.clipboard.writeText(invitation.invitation_url); setMessage("Invitation link copied."); }
        catch { setMessage("Select and copy the link above."); }
      }}>Copy link</Button></div>
    <p className="text-xs leading-relaxed text-muted-foreground">Share this link privately. It can be used once, before {new Date(invitation.expires_at).toLocaleString()}. The recipient sets their own password.</p>
    {message && <p role="status" className="text-sm text-primary">{message}</p>}
  </div>;
}
