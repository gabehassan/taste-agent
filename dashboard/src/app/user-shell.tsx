import Nav from "@/components/nav";
import { userApi } from "@/lib/user";

export async function me() {
  return userApi("/v1/me");
}

export default async function UserShell({ children, name }: { children: React.ReactNode; name: string }) {
  return (
    <div className="min-h-screen grain">
      <Nav name={name} />
      <main className="mx-auto max-w-5xl px-5 pb-24 pt-6">{children}</main>
    </div>
  );
}
