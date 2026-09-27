"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

/** Render children at the end of <body>, outside whatever they sit inside.
 *
 * An overlay must not be a descendant of the row that opened it. A completed
 * closure is dimmed with `opacity: 0.65` and a past one with `0.62`, and
 * opacity composites the whole subtree — a `position: fixed` panel included —
 * so the explanation and the permission notice came out faded, and doubly so
 * on a closure that was both. Ancestors are equally free to apply `transform`
 * or `filter` later, either of which would stop `position: fixed` being fixed
 * to the viewport at all. Escaping the tree fixes the class of bug rather
 * than this one instance of it.
 *
 * Nothing renders until after mount: the static export prerenders these
 * components at build time, where there is no `document` to portal into.
 */
export function Portal({ children }: { children: React.ReactNode }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted ? createPortal(children, document.body) : null;
}
