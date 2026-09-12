export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <div className="admin-root min-h-screen" style={{ background: "var(--paper)", color: "var(--ink)" }}>{children}</div>;
}
