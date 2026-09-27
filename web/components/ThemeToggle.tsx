"use client";

import { useEffect, useState } from "react";
import { Icon, PATH } from "./icons";

/** Light/dark toggle.
 *
 * The initial theme is applied by an inline script in the document head, so
 * the page never paints in the wrong theme first. This component only reads
 * back what that script decided and lets the user change it.
 */
export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const explicit = document.documentElement.dataset.theme;
    setDark(explicit
      ? explicit === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches);
  }, []);

  const toggle = () => {
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("bp-theme", next); } catch { /* private mode */ }
    setDark(!dark);
  };

  return (
    <button className="theme-btn" onClick={toggle} type="button"
      aria-pressed={dark} aria-label="Switch colour theme">
      <Icon d={dark ? PATH.sun : PATH.moon} size={15} />
      <span>{dark ? "Light mode" : "Dark mode"}</span>
    </button>
  );
}
