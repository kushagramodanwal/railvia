"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Icon, PATH } from "./icons";
import { ThemeToggle } from "./ThemeToggle";
import { usePlanner } from "./PlannerProvider";
import { useAuth } from "./AuthProvider";
import { ROLE_LABEL, DIVISIONS } from "@/lib/types";

/* Intake first: a defect exists before a plan for it does. */
const NAV = [
  { href: "/report", label: "Raise a job", icon: PATH.flag },
  { href: "/tonight", label: "Tonight", icon: PATH.clock },
  { href: "/calendar", label: "Calendar", icon: PATH.calendar },
  { href: "/plan", label: "Plan", icon: PATH.list },
  { href: "/map", label: "Map", icon: PATH.map },
  { href: "/approved", label: "Approved", icon: PATH.check },
  { href: "/completed", label: "Completed", icon: PATH.done },
];

export function Sidebar() {
  const path = usePathname();
  const { plan, approvals, completions, reports, division, setDivision } = usePlanner();
  const { me, session, signOut, error: authError } = useAuth();
  const [collapsed, setCollapsed] = useState(false);

  /* Reports waiting on the head, from the shared store. An emergency defect
     nobody has looked at is exactly the thing that must not need a click to
     discover, so the count rides on the nav from every view. */
  const waiting = reports.filter((r) => r.status === "open");
  const urgent = waiting.filter((r) => r.emergency).length;

  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--sidebar", collapsed ? "72px" : "236px");
  }, [collapsed]);

  /** Counts on the nav so the sidebar says what needs attention without
   *  making anyone open each view to find out. */
  const badge = (href: string): { text: string; warn?: boolean } | null => {
    // Checked before the plan guard: a waiting report matters whether or
    // not a plan has finished loading.
    if (href === "/report") {
      if (urgent) return { text: `${urgent}!`, warn: true };
      return waiting.length ? { text: String(waiting.length), warn: true } : null;
    }
    if (!plan) return null;
    if (href === "/tonight") {
      const t = Date.now(), end = t + 24 * 3600_000;
      const due = plan.blocks.filter((b) =>
        new Date(b.end).getTime() >= t && new Date(b.start).getTime() <= end);
      const ungranted = due.filter((b) => !approvals.has(`${b.section_id}@${b.start}`));
      if (!due.length) return null;
      return { text: String(due.length), warn: ungranted.length > 0 };
    }
    if (href === "/calendar") return { text: String(plan.block_count) };
    if (href === "/plan") {
      return plan.exceptions.length
        ? { text: String(plan.exceptions.length), warn: true }
        : { text: String(plan.block_count) };
    }
    if (href === "/map") {
      return { text: String(new Set(plan.blocks.map((b) => b.section_id)).size) };
    }
    if (href === "/approved") return { text: String(approvals.size) };
    return { text: String(completions.size) };
  };

  return (
    <aside className={"side" + (collapsed ? " collapsed" : "")}>
      <div className="brand">
        {!collapsed && (
          <div className="brand-main">
            <div>
              <b>RailVia</b>
            </div>
          </div>
        )}
        <button
          type="button"
          className="collapse-toggle"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-pressed={collapsed}
          onClick={() => setCollapsed((v) => !v)}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <span aria-hidden="true">{collapsed ? "›" : "‹"}</span>
        </button>
      </div>

      {/* Division Selector */}
      {!collapsed ? (
        <div className="division-picker">
          <div className="division-picker-label">
            <span>Select Division</span>
          </div>
          <div className="division-select-wrap">
            <select
              value={division.id}
              onChange={(e) => {
                const found = DIVISIONS.find((d) => d.id === e.target.value);
                if (found) setDivision(found);
              }}
              className="division-select"
              aria-label="Select Railway Division"
            >
              {DIVISIONS.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.id})
                </option>
              ))}
            </select>
            <div className="division-select-arrow" aria-hidden="true">▾</div>
          </div>
          <div className="division-zone-info">
            <span>{division.zone}</span>
          </div>
        </div>
      ) : (
        <div
          className="division-collapsed-chip"
          title={`${division.name} (${division.id}) · ${division.zone}`}
        >
          {division.id}
        </div>
      )}

      <nav aria-label="Views">
        {NAV.map((item) => {
          const b = badge(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={path === item.href ? "page" : undefined}
              title={collapsed ? item.label : undefined}
            >
              <Icon d={item.icon} size={16} />
              {!collapsed && <span className="nav-label">{item.label}</span>}
              {b && (
                <span className={"count" + (b.warn ? " warn" : "")}>{b.text}</span>
              )}
            </Link>
          );
        })}
      </nav>
      <div className="side-foot">
        {!collapsed && session && (
          <div className="who">
            <b>{me?.email ?? session.user.email}</b>
            <span className={"role" + (me?.role === "engineer" ? " eng" : "")
              + (me ? "" : " unknown")}
              title={me ? undefined : authError ?? "waiting for the API"}>
              {me ? ROLE_LABEL[me.role] : "role unknown"}
            </span>
          </div>
        )}
        {!collapsed && <ThemeToggle />}
        {!collapsed && session && (
          <button className="theme-btn" type="button" onClick={signOut}>
            Sign out
          </button>
        )}
      </div>
    </aside>
  );
}
