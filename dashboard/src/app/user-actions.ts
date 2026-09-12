"use server";
import { redirect } from "next/navigation";
import { revalidatePath } from "next/cache";
import { ApiError, publicApi, setUserKey, userApi } from "@/lib/user";

export async function requestLink(formData: FormData) {
  const phone = String(formData.get("phone") || "").trim();
  try { await publicApi("/v1/auth/request", { phone }); } catch (err) {
    const e = err instanceof ApiError ? (err.status === 429 ? "slow" : err.status === 422 ? "phone" : "unavailable") : "unavailable";
    redirect(`/login?e=${e}`);
  }
  redirect(`/login?sent=1&phone=${encodeURIComponent(phone)}`);
}

export async function enterExistingCode(formData: FormData) {
  const phone = String(formData.get("phone") || "").trim();
  redirect(`/login?sent=1&phone=${encodeURIComponent(phone)}`);
}

export async function exchangeCode(formData: FormData) {
  const phone = String(formData.get("phone") || "").trim();
  const token = String(formData.get("code") || "").trim();
  try {
    const r = await publicApi<{ key: string }>("/v1/auth/exchange", { token, phone });
    await setUserKey(r.key);
  } catch (err) {
    const e = err instanceof ApiError && err.status === 429 ? "slow" : "code";
    redirect(`/login?sent=1&phone=${encodeURIComponent(phone)}&e=${e}`);
  }
  redirect("/");
}

export async function saveSettings(formData: FormData) {
  const body: Record<string, unknown> = {
    name: formData.get("name") || undefined,
    tz: formData.get("tz") || undefined,
    surfaces_per_day: Number(formData.get("surfaces_per_day")),
    wake_start: Number(formData.get("wake_start")),
    wake_end: Number(formData.get("wake_end")),
    paused: formData.get("paused") === "on",
  };
  await userApi("/v1/me", { method: "PATCH", body: JSON.stringify(body) });
  revalidatePath("/settings"); revalidatePath("/");
}

export async function addConnection(formData: FormData) {
  const type = String(formData.get("type"));
  const config: Record<string, string> = {};
  for (const [k, v] of formData.entries()) if (k.startsWith("cfg_")) config[k.slice(4)] = String(v);
  await userApi("/v1/connections", { method: "POST", body: JSON.stringify({ type, config }) });
  revalidatePath("/connections");
}

export async function syncConnection(formData: FormData) {
  await userApi(`/v1/connections/${formData.get("cid")}/sync`, { method: "POST" });
  revalidatePath("/connections");
}

export async function removeConnection(formData: FormData) {
  await userApi(`/v1/connections/${formData.get("cid")}`, { method: "DELETE" });
  revalidatePath("/connections");
}

export async function setStatus(formData: FormData) {
  await userApi(`/v1/items/${formData.get("id")}`, { method: "PATCH", body: JSON.stringify({ status: formData.get("status") }) });
  revalidatePath("/items"); revalidatePath(`/items/${formData.get("id")}`); revalidatePath("/");
}

export async function saveUrl(formData: FormData) {
  await userApi("/v1/items/ingest", { method: "POST", body: JSON.stringify({ url: formData.get("url"), note: formData.get("note") || "", notify: false }) });
  redirect("/items?queued=1");
}

export async function surfaceNow() {
  await userApi("/v1/surface", { method: "POST" });
  revalidatePath("/");
}

export async function rebuildProfile() {
  await userApi("/v1/profile/refresh", { method: "POST" });
  revalidatePath("/taste");
}

export async function giveFeedback(_previous: { message: string; error: boolean }, formData: FormData) {
  const action = String(formData.get("action"));
  try {
    await userApi(`/v1/items/${Number(formData.get("id"))}/feedback`, { method: "POST", body: JSON.stringify({ action }) });
    revalidatePath("/"); revalidatePath("/items"); revalidatePath("/memory");
    return { message: action === "finished" ? "a little less saved for later." : action === "later" ? "resting for a few days." : "got it. that one can go.", error: false };
  } catch { return { message: "couldn't save that. try again.", error: true }; }
}

export async function rememberPreference(_previous: { message: string; error: boolean }, formData: FormData) {
  try {
    await userApi("/v1/me/memories", { method: "POST", body: JSON.stringify({ text: String(formData.get("text") || "") }) });
    revalidatePath("/memory");
    return { message: "I’ll keep that in mind.", error: false };
  } catch { return { message: "couldn't save that memory. there’s room for 30 notes; you can remove an old one below.", error: true }; }
}

export async function forgetPreference(formData: FormData) {
  await userApi(`/v1/me/memories/${encodeURIComponent(String(formData.get("id")))}`, { method: "DELETE" });
  revalidatePath("/memory");
}
