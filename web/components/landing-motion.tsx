"use client";

import { useEffect, useRef, useState } from "react";
import {
  LazyMotion, domAnimation, m,
  useInView, useReducedMotion, useScroll, useSpring,
} from "framer-motion";

/* Motion for the landing page.
 *
 * Kept in its own client module so the page stays a server component — only
 * these wrappers ship the animation runtime, not the whole page.
 *
 * The restraint is deliberate. This page argues that three closures should be
 * one; motion is here to help someone read that argument, not to decorate it.
 * So: things arrive from slightly below as they come into view, the rail down
 * the left draws itself as you scroll, and the three figures count up because
 * a number that lands is read, where a number that is simply present is
 * skimmed. Nothing parallaxes, nothing bounces, nothing loops forever.
 *
 * Every component here checks useReducedMotion and renders the finished state
 * immediately when it is set — not a faster animation, no animation.
 *
 * It uses `m` under a LazyMotion feature bundle rather than `motion`. This
 * page was 162 bytes of JavaScript before any of this; the full motion
 * component pulls in every feature whether or not it is used, and none of
 * what happens here needs drag, layout projection or SVG path morphing.
 */

const EASE = [0.22, 1, 0.36, 1] as const;   // a firm settle, no overshoot

/** Fade and rise into place when scrolled to. Once — a section that
 *  re-animates every time it passes the fold is a section nobody can read. */
export function Reveal({
  children, delay = 0, y = 18, className,
}: {
  children: React.ReactNode; delay?: number; y?: number; className?: string;
}) {
  const still = useReducedMotion();
  if (still) return <div className={className}>{children}</div>;
  return (
    <m.div
      className={className}
      data-reveal=""
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "0px 0px -12% 0px" }}
      transition={{ duration: 0.55, delay, ease: EASE }}
    >
      {children}
    </m.div>
  );
}

/** The hero, arriving in the order it is read: eyebrow, headline, lede,
 *  buttons, then the figure that carries the argument. */
export function Stagger({ children, className }: {
  children: React.ReactNode; className?: string;
}) {
  const still = useReducedMotion();
  if (still) return <div className={className}>{children}</div>;
  return (
    <m.div
      className={className}
      initial="hidden"
      animate="shown"
      variants={{ shown: { transition: { staggerChildren: 0.09 } } }}
    >
      {children}
    </m.div>
  );
}

export function StaggerItem({ children, className }: {
  children: React.ReactNode; className?: string;
}) {
  const still = useReducedMotion();
  if (still) return <div className={className}>{children}</div>;
  return (
    <m.div
      className={className}
      data-reveal=""
      variants={{
        hidden: { opacity: 0, y: 16 },
        shown: { opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE } },
      }}
    >
      {children}
    </m.div>
  );
}

/** The rail down the left of the page, drawing itself as you scroll.
 *
 * The spine is already there in CSS; this only scales it. It is the one piece
 * of motion tied to the subject rather than to the layout — the page lays
 * track as you travel down it. */
export function RailProgress() {
  const still = useReducedMotion();
  const { scrollYProgress } = useScroll();
  // Springing the raw progress stops the line twitching on a trackpad, which
  // a bare scroll value does badly.
  const scaleY = useSpring(scrollYProgress, {
    stiffness: 90, damping: 26, restDelta: 0.001,
  });

  if (still) return <div className="lp-rail" aria-hidden="true" />;
  return (
    <>
      {/* The line ahead, always there. A spine that started at zero height
          would read as a missing element rather than as one being drawn. */}
      <div className="lp-rail" aria-hidden="true" />
      {/* The line travelled, drawn over it. */}
      <m.div
        className="lp-rail lp-rail-draw"
        aria-hidden="true"
        style={{ scaleY, transformOrigin: "top" }}
      />
    </>
  );
}

/** A figure that counts up once, when it is reached.
 *
 * The three numbers on this page are the argument — 39 real sections, 7,267
 * counted movements, the percentage saved. A number that lands gets read; one
 * that is merely present gets skimmed. */
export function CountUp({
  to, prefix = "", suffix = "", decimals = 0, duration = 1.1,
}: {
  to: number; prefix?: string; suffix?: string;
  decimals?: number; duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true, margin: "0px 0px -15% 0px" });
  const still = useReducedMotion();
  const [n, setN] = useState(still ? to : 0);

  useEffect(() => {
    if (still || !inView) return;
    let raf = 0;
    const started = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / (duration * 1000));
      // Decelerating, so it arrives rather than stops dead.
      setN(to * (1 - Math.pow(1 - t, 3)));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, still, to, duration]);

  /* Grouped the way the static markup had them, so the number does not change
     shape when it settles. */
  const shown = n.toLocaleString(undefined, {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  });

  return (
    <span ref={ref} aria-label={`${prefix}${to.toLocaleString()}${suffix}`}>
      <span aria-hidden="true">{prefix}{shown}{suffix}</span>
    </span>
  );
}

/** The two calls to action. A small, quick lift — enough to feel like a
 *  control rather than a link, not enough to be a toy. */
export function Lift({ children, className }: {
  children: React.ReactNode; className?: string;
}) {
  const still = useReducedMotion();
  if (still) return <span className={className}>{children}</span>;
  return (
    <m.span
      className={className}
      style={{ display: "inline-flex" }}
      whileHover={{ y: -2 }}
      whileTap={{ y: 0, scale: 0.985 }}
      transition={{ duration: 0.18, ease: EASE }}
    >
      {children}
    </m.span>
  );
}

/** Loads the DOM animation features once for the whole page.
 *
 * `strict` makes the build fail on a stray `motion.*`, which would silently
 * pull the full bundle back in and undo the reason for using `m` at all. */
export function MotionRoot({ children }: { children: React.ReactNode }) {
  return (
    <LazyMotion features={domAnimation} strict>
      {children}
    </LazyMotion>
  );
}
