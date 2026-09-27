import type { Metadata } from "next";
import "./globals.css";
import "./landing.css";
import { AuthProvider } from "@/components/AuthProvider";

export const metadata: Metadata = {
  title: "RailVia",
  description:
    "Coordinated maintenance block scheduling for Indian Railways. "
    + "Traffic data is real; maintenance jobs are simulated.",
};

/* Set the theme before first paint. Without this the page renders in the
   default theme and then flips, which reads as a rendering fault. */
const THEME_BOOT = `
try {
  var t = localStorage.getItem('bp-theme');
  if (t) document.documentElement.dataset.theme = t;
} catch (e) {}
`;

/* The root layout carries only what every page needs. The sign-in gate and
   the planner shell moved into app/(app)/layout.tsx, so the landing page at
   / can be read without an account — a judge should not have to sign in to
   find out what this is. */
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: the boot script below sets data-theme on
    // <html> before React hydrates, so the server markup deliberately differs
    // from the client. This is the one case React sanctions suppressing.
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700;800&family=Archivo+Narrow:wght@500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Source+Sans+3:wght@400;600;700&display=swap" />
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} />
      </head>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
