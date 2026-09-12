import Link from "next/link";
import { Fade } from "@/components/motion";
import { onboardingConfig } from "@/lib/onboarding";

export default async function Start() {
  const config = await onboardingConfig();
  return (
    <main className="min-h-screen flex items-center justify-center p-6">
      <Fade className="w-full max-w-md">
        <div className="font-medium tracking-tight text-lg mb-2">taste</div>
        <h1 className="display text-3xl mb-5">a friend for everything you want to come back to.</h1>
        <p className="u-muted mb-8">send a link, a screenshot, or a stray thought. taste reads it, remembers it, and learns what you like.</p>
        {!config?.phone ? <p role="status" className="u-muted">messaging is temporarily unavailable. try again shortly.</p> : <>
          <p className="mb-5">{config.open_signup ? "text taste to get started. your first message creates your account." : "taste is in a small, invite-only beta. text your invite code to the number below to join."}</p>
          <a className="u-btn inline-block" href={`sms:${config.phone}`}>text taste</a>
          <div className="mono u-muted mt-3">{config.phone}</div>
          <p className="u-muted mt-6">then send something you want to remember. you can use taste entirely in Messages. the website is there when you want to browse your saves.</p>
          <p className="text-sm u-muted mt-4">taste replies with AI and can send things back throughout the day. text pause anytime to stop the scheduled texts.</p>
        </>}
        <div className="hair mt-8 pt-5 text-sm"><Link className="underline underline-offset-4" href="/login">already joined? log in</Link></div>
      </Fade>
    </main>
  );
}
