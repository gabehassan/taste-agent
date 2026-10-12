import Nav from "@/components/nav";
import type { Me } from "@/lib/types";
import { userApi } from "@/lib/user";

export async function me() {
  return userApi<Me>("/v1/me");
}

export default async function UserShell({ children, name }: { children: React.ReactNode; name: string }) {
  return (
    <div className="min-h-screen">
      <Nav name={name} />
      <main className="mx-auto max-w-[1160px] px-5 md:px-8 pb-24 pt-10">{children}</main>
    </div>
  );
}
