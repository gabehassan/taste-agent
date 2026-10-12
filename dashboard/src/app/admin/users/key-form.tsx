"use client";
import { useActionState } from "react";
import { createKeyAction } from "../actions";

export default function KeyForm({ uid }: { uid: string }) {
  const [state, action, pending] = useActionState(createKeyAction, { key: "", error: "" });
  return <>
    <form action={action} className="flex gap-1 mt-2">
      <input type="hidden" name="uid" value={uid} />
      <input name="name" placeholder="name" className="w-24" />
      <select name="scope"><option value="transport">transport</option><option value="user">user</option><option value="admin">admin</option></select>
      <button className="ghost" disabled={pending}>{pending ? "creating…" : "new key"}</button>
    </form>
    {state.error && <p role="alert" className="mt-2">{state.error}</p>}
    {state.key && <div role="status" className="mt-2"><div className="muted text-xs uppercase">new key (shown once, copy it now)</div><code className="block mt-1 break-all select-all">{state.key}</code></div>}
  </>;
}
