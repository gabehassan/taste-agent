import Link from "next/link";
import { Fade } from "@/components/motion";
import { onboardingConfig } from "@/lib/onboarding";
import { loginPhone } from "@/lib/user";
import { enterExistingCode, exchangeCode, requestLink } from "../user-actions";

export default async function Login({ searchParams }: { searchParams: Promise<{ sent?: string; e?: string }> }) {
  const { sent, e } = await searchParams;
  const phone = await loginPhone();
  const config = await onboardingConfig();
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <Fade className="w-full max-w-sm">
        <div className="font-medium tracking-tight text-lg mb-1">taste</div>
        <p className="u-muted mb-8">the friend who reads everything you send, and remembers.</p>
        {sent ? (
          <>
            <form action={exchangeCode} className="flex flex-col gap-3">
              <label htmlFor="code" className="mono u-muted">enter your 6-digit login code</label>
              <p className="text-sm u-muted">use the latest code for {phone}. codes last 10 minutes.</p>
              <input type="hidden" name="phone" value={phone} />
              <input id="code" name="code" inputMode="numeric" pattern="[0-9 ]*" maxLength={11} autoComplete="one-time-code" placeholder="000000" required autoFocus className="u-input mono" style={{ fontSize: 22, letterSpacing: ".3em", textAlign: "center", padding: 14 }} aria-describedby={e ? "login-error" : undefined} />
              {e && <div id="login-error" role="alert" className="text-sm u-muted">{e === "slow" ? "too many attempts. wait a bit before trying again." : "that code didn't work. use the latest code or request a new one."}</div>}
              <button className="u-btn">log in</button>
            </form>
            <form action={requestLink} className="mt-4">
              <input type="hidden" name="phone" value={phone} />
              <button className="text-sm underline underline-offset-4">request a new code</button>
            </form>
            <p className="text-sm u-muted mt-4">if you’ve already joined, check Messages. {config?.phone && <>you can also text <b>login</b> to <a href={`sms:${config.phone}`} className="underline">{config.phone}</a>. </>}<Link href="/login" className="underline">different number</Link></p>
          </>
        ) : (
          <form action={requestLink} className="flex flex-col gap-3">
            <label className="mono u-muted" htmlFor="phone">the number you use to text taste</label>
            <input id="phone" name="phone" type="tel" inputMode="tel" autoComplete="tel" placeholder="+1 313 555 0123" maxLength={40} required autoFocus className="u-input" />
            {e && <div role="alert" className="text-sm u-muted">{e === "expired" ? "that session ended. get a fresh code." : e === "phone" ? "enter your phone number with its country code." : e === "unavailable" ? "couldn't request a code. try again shortly." : "too many requests. wait a bit before trying again."}</div>}
            <button className="u-btn">text me a code</button>
            <button formAction={enterExistingCode} className="u-btn soft">I already have a code</button>
          </form>
        )}
        <p className="hair text-sm u-muted mt-8 pt-5">new here? <Link href="/start" className="underline underline-offset-4">{config?.open_signup ? "start by texting taste" : "join with an invite"}</Link>. logging in here won’t create an account.</p>
      </Fade>
    </main>
  );
}
