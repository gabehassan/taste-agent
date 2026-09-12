import { Fade } from "@/components/motion";
import { exchangeCode, requestLink } from "../user-actions";

export default async function Login({ searchParams }: { searchParams: Promise<{ sent?: string; e?: string; phone?: string }> }) {
  const { sent, e, phone } = await searchParams;
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <Fade className="w-full max-w-sm">
        <div className="font-medium tracking-tight text-lg mb-1">taste</div>
        <p className="u-muted mb-10">the friend who reads everything you send, and remembers.</p>
        {sent ? (
          <form action={exchangeCode} className="flex flex-col gap-3">
            <div className="mono u-faint">I texted you a 6-digit code</div>
            <input type="hidden" name="phone" value={phone || ""} />
            <input name="code" inputMode="numeric" pattern="[0-9 ]*" autoComplete="one-time-code" placeholder="000000" required autoFocus className="u-input mono" style={{ fontSize: 22, letterSpacing: ".3em", textAlign: "center", padding: 14 }} />
            {e === "code" && <div className="text-sm u-muted">that code didn't work. codes last 10 minutes.</div>}
            <button className="u-btn">enter</button>
            <p className="mono u-faint">nothing? text <b>login</b> to the number instead. <a href="/login" className="underline">different number</a></p>
          </form>
        ) : (
          <form action={requestLink} className="flex flex-col gap-3">
            <label className="mono u-faint" htmlFor="phone">your number</label>
            <input id="phone" name="phone" type="tel" inputMode="tel" placeholder="+1 313 555 0123" required autoFocus className="u-input" />
            {e === "expired" && <div className="text-sm u-muted">that session ended. get a fresh code.</div>}
            {e === "slow" && <div className="text-sm u-muted">easy. try again in a bit.</div>}
            <button className="u-btn">text me a code</button>
            <p className="mono u-faint">no passwords. your phone is the key. invite only for now.</p>
          </form>
        )}
      </Fade>
    </main>
  );
}
