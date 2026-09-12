import { redirect } from "next/navigation";
import { publicApi, setUserKey } from "@/lib/user";

export default async function Auth({ searchParams }: { searchParams: Promise<{ token?: string }> }) {
  const { token } = await searchParams;
  if (!token) redirect("/login");
  try {
    const r = await publicApi<{ key: string }>("/v1/auth/exchange", { token });
    await setUserKey(r.key);
  } catch {
    redirect("/login?e=expired");
  }
  redirect("/");
}
