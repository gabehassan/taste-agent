"use client";
import { useActionState } from "react";
import { createInviteAction } from "../actions";

export default function InviteForm() {
  const [state, action, pending] = useActionState(createInviteAction, { token: "", error: "" });
  return <div className="card mb-6">
    <h2 className="font-medium mb-2">invite someone to taste</h2>
    <p className="muted text-sm mb-3">each code works once and expires in 7 days. share the code and the <a href="/start" className="underline">getting started page</a>.</p>
    <form action={action} className="flex flex-wrap gap-2">
      <label className="sr-only" htmlFor="invite-email">email (optional)</label>
      <input id="invite-email" name="email" type="email" placeholder="email (optional)" />
      <button disabled={pending}>{pending ? "creating…" : "create invite"}</button>
    </form>
    {state.error && <p role="alert" className="mt-3">{state.error}</p>}
    {state.token && <div role="status" className="mt-4"><div className="muted text-sm">copy this code now. ask them to text it to taste.</div><code className="block mt-2 break-all select-all">{state.token}</code></div>}
  </div>;
}
