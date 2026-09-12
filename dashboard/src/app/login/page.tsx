import { Fade, Words } from "@/components/motion";
import { exchangeCode, requestLink } from "../user-actions";

export default async function Login({ searchParams }: { searchParams: Promise<{ sent?: string; e?: string; phone?: string }> }) {
  const { sent, e, phone } = await searchParams;
  return (
    <main className="min-h-screen grain flex items-center justify-center p-6">
      <div className="w-full max-w-md">
        <Fade><div className="display text-6xl mb-2">taste<span style={{ color: "var(--accent)" }}>.</span></div></Fade>
        <Fade delay={0.1}><p className="u-muted text-lg mb-8"><Words text="the friend who reads everything you send, and remembers." delay={0.15} /></p></Fade>
        <Fade delay={0.35}>
          {sent ? (
            <form action={exchangeCode} className="u-card p-6 flex flex-col gap-3">
              <div className="u-kicker">check your messages</div>
              <p className="u-muted text-sm">if that number is yours, I just texted you a 6-digit code.</p>
              <input type="hidden" name="phone" value={phone || ""} />
              <input name="code" inputMode="numeric" pattern="[0-9 ]*" autoComplete="one-time-code" placeholder="000000" required autoFocus className="u-input tracking-[.35em] text-2xl text-center" />
              {e === "code" && <div className="text-sm" style={{ color: "var(--accent)" }}>that code didn't work. codes last 10 minutes.</div>}
              <button className="u-btn">let me in</button>
              <p className="u-faint text-xs">nothing? text me the word <b>login</b> from that phone instead. <a href="/login" className="underline">different number</a></p>
            </form>
          ) : (
            <form action={requestLink} className="u-card p-6 flex flex-col gap-3">
              <label className="u-kicker" htmlFor="phone">your number</label>
              <input id="phone" name="phone" type="tel" inputMode="tel" placeholder="+1 313 555 0123" required autoFocus className="u-input" />
              {e === "expired" && <div className="text-sm" style={{ color: "var(--accent)" }}>that session ended. text yourself a fresh link.</div>}
              {e === "slow" && <div className="text-sm" style={{ color: "var(--accent)" }}>easy. try again in a bit.</div>}
              <button className="u-btn mt-1">text me a login link</button>
              <p className="u-faint text-xs">no passwords. your phone is the key. invite only for now.</p>
            </form>
          )}
        </Fade>
      </div>
    </main>
  );
}
