"use server";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { api } from "@/lib/api";
import { clientIp } from "@/lib/client-ip";
import { clearSession, requireSession, loginAllowed, passwordOk, setCurrentUserId, setSession } from "@/lib/session";

export async function login(formData: FormData) {
  if (!loginAllowed((await clientIp()) ?? "unknown")) redirect("/admin/login?e=slow");
  if (!passwordOk(String(formData.get("password") || ""))) redirect("/admin/login?e=bad");
  await setSession();
  redirect("/admin");
}

export async function logout() { await clearSession(); redirect("/admin/login"); }

export async function pickUser(formData: FormData) {
  await requireSession();
  await setCurrentUserId(String(formData.get("uid")));
  revalidatePath("/admin", "layout");
}

export async function createUser(formData: FormData) {
  await api("/v1/admin/users", { method: "POST", body: JSON.stringify({
    name: formData.get("name"), email: formData.get("email") || null, role: formData.get("role") || "user", tz: formData.get("tz") || "UTC",
    handles: String(formData.get("handles") || "").split(",").map(s => s.trim()).filter(Boolean),
  }) });
  revalidatePath("/admin/users");
}

export async function patchUser(uid: string, patch: Record<string, unknown>) {
  await api(`/v1/admin/users/${uid}`, { method: "PATCH", body: JSON.stringify(patch) });
  revalidatePath("/admin/users");
}

export async function setUserCap(formData: FormData) {
  await patchUser(String(formData.get("uid")), { settings: { daily_spend_cap_usd: Number(formData.get("cap")) } });
}

export async function toggleUser(formData: FormData) {
  await patchUser(String(formData.get("uid")), { status: formData.get("status") });
}

export async function addHandle(formData: FormData) {
  await api(`/v1/admin/users/${formData.get("uid")}/handles`, { method: "POST", body: JSON.stringify({ address: formData.get("address") }) });
  revalidatePath("/admin/users");
}

// The raw key is returned to the form that asked for it and shown once. It never goes into a URL,
// where it would land in browser history and request logs.
export async function createKeyAction(_previous: { key: string; error: string }, formData: FormData) {
  try {
    const r = await api(`/v1/admin/users/${formData.get("uid")}/keys`, { method: "POST", body: JSON.stringify({ name: formData.get("name") || "key", scopes: [String(formData.get("scope") || "transport")] }) });
    revalidatePath("/admin/users");
    return { key: r.key as string, error: "" };
  } catch {
    return { key: "", error: "Couldn't create a key. Try again." };
  }
}

export async function revokeKey(formData: FormData) {
  await api(`/v1/admin/keys/${formData.get("kid")}`, { method: "DELETE" });
  revalidatePath("/admin/users");
}

export async function saveSettings(formData: FormData) {
  const body: Record<string, unknown> = {};
  for (const [k, v] of formData.entries()) {
    if (k === "model_prices") { try { body[k] = JSON.parse(String(v)); } catch { redirect("/admin/settings?e=json"); } }
    else if (k.startsWith("$")) continue;
    else body[k] = Number(v);
  }
  await api("/v1/admin/settings", { method: "PUT", body: JSON.stringify(body) });
  revalidatePath("/admin/settings");
}

export async function addConnection(formData: FormData) {
  const uid = String(formData.get("uid"));
  const type = String(formData.get("type"));
  const config: Record<string, string> = {};
  for (const [k, v] of formData.entries()) if (k.startsWith("cfg_")) config[k.slice(4)] = String(v);
  await api("/v1/connections", { method: "POST", userId: uid, body: JSON.stringify({ type, config }) });
  revalidatePath("/admin/connections");
}

export async function syncConnection(formData: FormData) {
  await api(`/v1/connections/${formData.get("cid")}/sync`, { method: "POST", userId: String(formData.get("uid")) });
  revalidatePath("/admin/connections");
}

export async function deleteConnection(formData: FormData) {
  await api(`/v1/connections/${formData.get("cid")}`, { method: "DELETE", userId: String(formData.get("uid")) });
  revalidatePath("/admin/connections");
}

export async function ingestUrl(formData: FormData) {
  await api("/v1/items/ingest", { method: "POST", userId: String(formData.get("uid")), body: JSON.stringify({ url: formData.get("url"), note: formData.get("note") || "", notify: formData.get("notify") === "on" }) });
  revalidatePath("/admin/items");
}

export async function patchItem(formData: FormData) {
  await api(`/v1/items/${formData.get("id")}`, { method: "PATCH", userId: String(formData.get("uid")), body: JSON.stringify({ status: formData.get("status") }) });
  revalidatePath("/admin/items");
}

export async function deleteItem(formData: FormData) {
  await api(`/v1/items/${formData.get("id")}`, { method: "DELETE", userId: String(formData.get("uid")) });
  redirect("/admin/items");
}

export async function refreshProfile(formData: FormData) {
  await api("/v1/profile/refresh", { method: "POST", userId: String(formData.get("uid")) });
  revalidatePath("/admin/profile");
}

export async function surfaceNow(formData: FormData) {
  await api("/v1/surface", { method: "POST", userId: String(formData.get("uid")) });
  revalidatePath("/admin/logs");
}

export async function retryJob(formData: FormData) {
  await api(`/v1/admin/jobs/${formData.get("jid")}/retry`, { method: "POST" });
  revalidatePath("/admin/logs");
}

export async function createInviteAction(_previous: { token: string; error: string }, formData: FormData) {
  await requireSession();
  try {
    const result = await api("/v1/admin/invites", { method: "POST", body: JSON.stringify({
      email: formData.get("email") || null, role: "user", days: 7,
    }) });
    revalidatePath("/admin/users");
    return { token: result.token as string, error: "" };
  } catch {
    return { token: "", error: "Couldn't create an invite. Try again." };
  }
}
