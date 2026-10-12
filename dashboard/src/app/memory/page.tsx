import UserShell, { me } from "../user-shell";
import MemoryView from "@/components/memory-view";
import PreferenceForm from "@/components/preference-form";
import TasteMark from "@/components/taste-mark";
import { Fade } from "@/components/motion";
import type { MemorySnapshot } from "@/lib/types";
import { userApi } from "@/lib/user";
import { forgetPreference } from "../user-actions";

export default async function Memory() {
  const [m0, m] = await Promise.all([me(), userApi<MemorySnapshot>("/v1/me/memory")]);
  return <UserShell name={m0.user.name || ""}>
    <Fade><div className="memory-intro"><div><div className="mono u-muted mb-5">a little more like you</div><h1 className="display text-4xl md:text-5xl">what stays with me.</h1><p className="u-muted mt-5 max-w-lg">the things you tell me, the patterns I’m beginning to notice, and room to change my mind. this is your memory. you can correct it.</p></div><TasteMark /></div></Fade>
    <div className="memory-grid">
      <section><div className="section-label"><h2>in your own words</h2><span className="mono u-muted">{m.preferences?.length || 0} notes</span></div>
        <div className="memory-notes">{(m.preferences || []).map(pref => <article key={pref.id} className="memory-note"><p>{pref.text}</p><div className="flex items-center justify-between mt-4"><span className="mono u-muted">{pref.source === "conversation" ? "from our conversation" : "you told me"}</span><form action={forgetPreference}><input type="hidden" name="id" value={pref.id} /><button className="text-xs u-muted underline underline-offset-4">forget</button></form></div></article>)}</div>
        {!m.preferences?.length && <p className="u-muted text-sm py-5">nothing assumed. tell me something worth remembering, here or in Messages.</p>}
        <PreferenceForm />
      </section>
      <section className="memory-learned"><div className="mono u-muted mb-5">what I’m noticing</div><p className="text-xl leading-relaxed">{m.profile?.one_liner || "a few saves are a beginning, not a personality. I’m listening."}</p>
        {(m.profile?.observations || []).slice(0, 3).map(observation => <p key={observation} className="hair pt-4 mt-5 u-muted text-sm">{observation}</p>)}
        <p className="mono u-muted mt-8">a working impression. never the whole of you.</p>
      </section>
    </div>
    <details className="memory-detail"><summary>look a little closer <span className="u-muted">conversation, voice & how memory works</span></summary><div className="pt-8"><MemoryView m={m} /></div></details>
  </UserShell>;
}
