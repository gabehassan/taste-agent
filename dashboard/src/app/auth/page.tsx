import { redirect } from "next/navigation";

// Old magic links are no longer credentials. Login requires phone + six-digit code.
export default function Auth() {
  redirect("/login?e=expired");
}
