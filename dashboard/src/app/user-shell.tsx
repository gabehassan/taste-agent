import Nav from "@/components/nav";
import { userApi } from "@/lib/user";

export async function me() {
  return userApi("/v1/me");
}

export default async function UserShell({ children, name }: { children: React.ReactNode; name: string }) {
  return (
    <div className="min-h-screen">
      <Nav name={name} />
      <main className="mx-auto max-w-[1400px] px-6 pb-32 pt-8">{children}</main>
    </div>
  );
}
