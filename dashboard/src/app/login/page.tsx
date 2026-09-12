import { login } from "../actions";

export default async function Login({ searchParams }: { searchParams: Promise<{ e?: string }> }) {
  const { e } = await searchParams;
  return (
    <div className="min-h-screen flex items-center justify-center">
      <form action={login} className="card w-80 flex flex-col gap-3">
        <div className="text-lg font-semibold">taste admin</div>
        <input type="password" name="password" placeholder="password" autoFocus required />
        {e === "bad" && <div className="text-red-400 text-sm">wrong password</div>}
        {e === "slow" && <div className="text-red-400 text-sm">too many attempts, wait 15 minutes</div>}
        <button>log in</button>
      </form>
    </div>
  );
}
