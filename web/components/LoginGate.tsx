"use client";

import { useState } from "react";
import { useAuth } from "./AuthProvider";
import { Icon, PATH } from "./icons";
import { TrainLoader } from "./TrainLoader";

/** Everything behind a sign-in.
 *
 * Two roles exist: a divisional head, who grants closures, and a section
 * engineer, who reports work done. Which one you are is read from Postgres,
 * not chosen here.
 */
/** Supabase answers "Invalid login credentials" for three quite different
 *  situations, deliberately, so an attacker cannot discover which accounts
 *  exist. That is right for production and unhelpful while setting up, so we
 *  name the three possibilities rather than repeating the bare message. */
function explain(raw: string): string {
  if (/invalid login credentials/i.test(raw)) {
    return "Invalid login credentials. Supabase gives the same message "
      + "whether the account does not exist, the password is wrong, or the "
      + "email has never been confirmed — check Authentication → Users in the "
      + "Supabase dashboard, and make sure the account shows as confirmed.";
  }
  if (/email not confirmed/i.test(raw)) {
    return "That account exists but its email is not confirmed. Confirm it "
      + "in Authentication → Users, or recreate it with “Auto Confirm User” "
      + "ticked.";
  }
  if (/fetch|network/i.test(raw)) {
    return "Could not reach Supabase. Check NEXT_PUBLIC_SUPABASE_URL in "
      + "web/.env.local, and restart the dev server — Next only reads env "
      + "files at startup.";
  }
  return raw;
}

export function LoginGate({ children }: { children: React.ReactNode }) {
  const { session, loading, configured } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const { signIn } = useAuth();

  if (loading) {
    return (
      <div className="tl-wrap tl-route">
        <TrainLoader label="Checking your session" />
        <div className="tl-say">Checking your session…</div>
      </div>
    );
  }
  if (session) return <>{children}</>;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { await signIn(email.trim(), password); }
    catch (e2) {
      const raw = e2 instanceof Error ? e2.message : String(e2);
      setErr(explain(raw));
    }
    finally { setBusy(false); }
  };

  return (
    <div className="login-wrap">
      <div className="login">
        <div className="brand" style={{ padding: 0, marginBottom: 20 }}>
          <span className="mark" aria-hidden="true"><Icon d={PATH.rail} size={14} /></span>
          <b>RailVia</b>
        </div>

        {!configured ? (
          <div className="setup">
            <h3>Supabase is not configured</h3>
            <div className="note">Sign-in needs a Supabase project. Create
              <code> web/.env.local</code> with:</div>
            <pre>{`NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon key>`}</pre>
            <div className="note">
              Then run <code>src/store/schema.sql</code> in the SQL editor and
              add the two users, as described at the bottom of that file.
            </div>
          </div>
        ) : (
          <form onSubmit={submit}>
            <h2 style={{ margin: "0 0 4px", fontSize: 17 }}>Sign in</h2>
            <p className="note" style={{ marginBottom: 18 }}>
              A <b>divisional head</b> grants closures. A <b>section engineer</b>
              {" "}reports work as done.
            </p>
            <label htmlFor="email">Email</label>
            <input id="email" type="email" autoComplete="username" required
              value={email} onChange={(e) => setEmail(e.target.value)} />
            <label htmlFor="password">Password</label>
            <input id="password" type="password" autoComplete="current-password"
              required value={password}
              onChange={(e) => setPassword(e.target.value)} />
            {err && <div className="login-err">{err}</div>}
            <button type="submit" className="primary" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        )}
      </div>
    </div>
  );
}
