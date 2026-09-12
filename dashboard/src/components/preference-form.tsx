"use client";
import { useActionState } from "react";
import { rememberPreference } from "@/app/user-actions";

export default function PreferenceForm() {
  const [state, action, pending] = useActionState(rememberPreference, { message: "", error: false });
  return <form action={action} className="preference-form">
    <label htmlFor="preference" className="text-sm block mb-3">something I should know about you</label>
    <textarea id="preference" name="text" required maxLength={500} rows={3} className="u-input resize-none" placeholder="the details matter. an artist you always return to, a topic you’re tired of, the kind of thing you wish you read more…" />
    <div className="flex flex-wrap items-center gap-4 mt-3"><button disabled={pending} className="u-btn">{pending ? "remembering…" : "remember this"}</button><span role={state.error ? "alert" : "status"} className="text-xs u-muted">{state.message}</span></div>
  </form>;
}
