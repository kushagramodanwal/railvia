"use client";

import { usePlanner } from "./PlannerProvider";
import { TrainLoader } from "./TrainLoader";

export const Fact = ({ value, label, tone, progress }: {
  value: string;
  label: string;
  tone?: "win" | "warn";
  progress?: number;
}) => (
  <div className={"kpi-card" + (tone ? " " + tone : "")}>
    <div className="kpi-head">
      <span className="kpi-label">{label}</span>
    </div>
    <div className="kpi-val">{value}</div>
    {progress !== undefined && (
      <div className="kpi-progress">
        <div className="kpi-progress-bar" style={{ width: `${Math.min(100, Math.max(0, progress))}%` }} />
      </div>
    )}
  </div>
);

export function Loading({ what }: { what: string }) {
  return (
    <>
      <div className="tl-wrap">
        <TrainLoader label={what} />
        <div className="tl-say">{what}</div>
      </div>
      {[0, 1, 2].map((i) => <div className="sk" key={i} />)}
    </>
  );
}

export function SetupBanner() {
  const { store } = usePlanner();
  return (
    <div className="setup">
      <h3>Supabase is not connected</h3>
      <div className="note">
        Approvals and completions are stored in Supabase only — there is no
        local fallback, so two planners can never approve different things
        without finding out. The API needs its own credentials, separately
        from the ones this page was built with.
      </div>
      <pre>{`Set on the server (Render → Environment, or .env locally):

  SUPABASE_URL=https://<project>.supabase.co
  SUPABASE_KEY=<anon key>

then restart the API.`}</pre>
      <div className="note">
        These are the server-side pair. The two <code>NEXT_PUBLIC_</code>
        {" "}variables are compiled into this page and are already working —
        you are signed in.
      </div>
      {store?.detail && <div className="note">{store.detail}</div>}
    </div>
  );
}
