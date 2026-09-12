import UserShell, { me } from "../user-shell";
import MemoryView from "@/components/memory-view";
import { Fade } from "@/components/motion";
import { userApi } from "@/lib/user";

export default async function Memory() {
  const m0 = await me();
  const m = await userApi("/v1/me/memory");
  return (
    <UserShell name={m0.user.name || ""}>
      <Fade><h1 className="display text-4xl pt-6">memory</h1></Fade>
      <MemoryView m={m} />
    </UserShell>
  );
}
