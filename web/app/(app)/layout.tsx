import { LoginGate } from "@/components/LoginGate";
import { PlannerProvider } from "@/components/PlannerProvider";
import { Sidebar } from "@/components/Sidebar";

/* Everything behind the sign-in. The landing page at / sits outside this
   group, so it renders without an account and without paying for a solve. */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <LoginGate>
        <PlannerProvider>
          <div className="shell">
            <Sidebar />
            <main className="content" id="main">{children}</main>
          </div>
        </PlannerProvider>
      </LoginGate>
    </>
  );
}
