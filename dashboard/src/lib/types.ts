// Response shapes from the taste API. Only the fields the dashboard reads are listed.

export type UserSettings = {
  daily_spend_cap_usd?: number;
  surfaces_per_day?: number;
  wake_start?: number;
  wake_end?: number;
  paused?: boolean;
};

export type User = {
  id: string;
  name: string | null;
  email: string | null;
  role: string;
  status: string;
  tz: string;
  transport: string;
  settings: UserSettings;
  created_at: string;
};

export type Handle = { id: string; kind: string; address: string; capabilities: string[] | null; last_seen_at: string | null };

export type KeySummary = {
  id: string;
  name: string | null;
  prefix: string;
  scopes: string[];
  last_used_at: string | null;
  revoked_at: string | null;
};

export type AdminUser = User & {
  items: number;
  handles: Handle[] | null;
  keys: KeySummary[] | null;
  spend_today: number;
  spend_month: number;
};

export type ItemMeta = {
  thumbnail?: string;
  author_avatar?: string;
  reactions?: string[];
  rating?: number | null;
};

export type Item = {
  id: number;
  url: string | null;
  kind: string;
  source: string | null;
  title: string | null;
  author: string | null;
  summary: string | null;
  snippets: string[];
  tags: string[];
  why: string | null;
  note: string | null;
  read_minutes: number;
  status: string;
  meta: ItemMeta;
  surfaced_count: number;
  last_surfaced_at: string | null;
  created_at: string;
  raw_text?: string | null;
  transcript?: string | null;
  media_urls?: string[];
};

export type ItemList = { items: Item[]; total: number };

export type Profile = {
  id: number;
  text: string;
  observations: string[];
  one_liner: string | null;
  item_count: number;
  created_at: string;
};

export type ProfileResponse = {
  profile: Profile | null;
  history: { id: number; created_at: string; item_count: number }[];
};

export type Me = {
  user: User;
  counts: { items: number; unread: number; read: number };
  one_liner: string | null;
  spend_today: number;
};

export type Connection = {
  id: string;
  type: string;
  config: Record<string, string>;
  status: string;
  last_synced_at: string | null;
  last_error: string | null;
};

export type ConnectionType = { label: string; config: string[]; multi: boolean };

export type Connections = { connections: Connection[]; types: Record<string, ConnectionType> };

export type Preference = { id: string; text: string; source: string; evidence?: string };

export type MessageRow = {
  id: number;
  direction: "in" | "out";
  kind: string;
  text: string | null;
  status: string;
  created_at: string;
  meta?: { emoji?: string; reaction?: string; target_external_id?: string; error?: string };
  name?: string | null;
};

export type ChatTurn = { role: string; content: string };

export type MemorySnapshot = {
  user: User;
  voice: { stats: { n?: number; avg_len?: number; lowercase?: number; emoji?: number; exclaim?: number }; sentence: string; rendered: string };
  profile: Profile | null;
  preferences: Preference[];
  profile_history: { id: number; created_at: string; item_count: number; one_liner: string | null }[];
  chat_memory: ChatTurn[];
  recent_texts: MessageRow[];
  reactions: { item_id: number; title: string; reactions: string[] }[];
  tags: { tag: string; n: number }[];
  schedule: {
    plan: { date: string; slots: { at: string; done: boolean }[] } | null;
    settings: UserSettings;
    items_since_profile: number;
  };
  spend: { today: number; month: number };
  prompts: { digest: string; chat: string; profile: string; about: Record<"voice" | "digest" | "chat" | "profile", string> };
};

export type Overview = {
  users: number;
  items: number;
  jobs: Record<string, number>;
  spend: { today: number; month: number };
  caps: { global_daily: number; global_monthly: number };
  messages_24h: { in?: number; out?: number };
  storage: { bytes?: number; objects?: number; error?: string } | null;
};

export type Job = { id: number; type: string; status: string; attempts: number; error: string | null; created_at: string };

export type AuditEntry = { id: number; action: string; detail: unknown; created_at: string };

export type Usage = {
  by_day: { day: string; cost: number }[];
  by_model: { model: string; kind: string; calls: number; input_tokens: number; output_tokens: number; cost: number }[];
};

export type Settings = Record<string, number | boolean | Record<string, unknown>>;
