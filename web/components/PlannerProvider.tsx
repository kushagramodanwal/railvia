"use client";

import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
} from "react";
import {
  approve as apiApprove, completeJob, DEFAULT_PARAMS, getDecisions, getPlan,
  getReports, getStore, PlanParams, unapprove as apiUnapprove, uncompleteJob,
} from "@/lib/api";
import type {
  Approval, Block, Completion, Division, Plan, Report, StoreStatus,
} from "@/lib/types";
import { blockKey, DIVISIONS } from "@/lib/types";
import { useAuth } from "./AuthProvider";

/** One provider for the whole app.
 *
 * Every view needs the same plan and the same decisions, and a solve costs up
 * to a minute — so it is fetched once here and shared, rather than each route
 * re-requesting it. Decisions are keyed by instance_id, so plan and decisions
 * must always be loaded together or approvals would attach to the wrong plan.
 */
interface Ctx {
  plan: Plan | null;
  store: StoreStatus | null;
  approvals: Map<string, Approval>;
  completions: Map<string, Completion>;
  /** Field reports, shared so the sidebar badge and the calendar's emergency
   *  banner come from one fetch rather than each view asking separately. */
  reports: Report[];
  reloadReports: () => void;
  /** Why reports could not be loaded — most often the `reports` table has
   *  not been created yet, which the intake page names specifically. */
  reportsError: string | null;
  params: PlanParams;
  division: Division;
  setDivision: (d: Division) => void;
  loading: boolean;
  error: string | null;
  setParams: (p: Partial<PlanParams>) => void;
  reload: () => void;
  toggleApproval: (b: Block) => Promise<void>;
  toggleDone: (b: Block) => Promise<void>;
  isApproved: (b: Block) => boolean;
  isDone: (b: Block) => boolean;
}

const PlannerContext = createContext<Ctx | null>(null);

export const usePlanner = () => {
  const ctx = useContext(PlannerContext);
  if (!ctx) throw new Error("usePlanner must be used inside PlannerProvider");
  return ctx;
};

export function PlannerProvider({ children }: { children: React.ReactNode }) {
  const { session } = useAuth();
  const token = session?.access_token;
  const [division, setDivision] = useState<Division>(DIVISIONS[0]);
  const [params, setParamsState] = useState<PlanParams>(DEFAULT_PARAMS);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [store, setStore] = useState<StoreStatus | null>(null);
  const [approvals, setApprovals] = useState<Map<string, Approval>>(new Map());
  const [completions, setCompletions] = useState<Map<string, Completion>>(new Map());
  const [reports, setReports] = useState<Report[]>([]);
  const [reportsError, setReportsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    /* The plan first, and on its own.
     *
     * This used to await the store before the plan. The store only says
     * whether decisions can be recorded — the plan needs it for nothing —
     * but a Supabase that hangs rather than fails takes the catch with it,
     * and the whole app sat on "Loading…" forever. Measured: the plan came
     * back in 3ms while the store took over twenty seconds.
     *
     * So the page draws as soon as it has a plan, and everything to do with
     * the store arrives afterwards or not at all. */
    (async () => {
      try {
        const p = await getPlan(params);
        if (cancelled) return;
        setPlan(p);
        setLoading(false);

        const status = await getStore().catch(
          (): StoreStatus => ({
            connected: false, backend: "Supabase", shared: true,
            detail: "Could not reach the store — planning is unaffected, "
              + "but approvals and completions cannot be recorded.",
          }),
        );
        if (cancelled) return;
        setStore(status);

        if (status.connected && token) {
          try {
            const d = await getDecisions(p.instance_id, token);
            if (cancelled) return;
            setApprovals(new Map(d.approvals.map((a) => [
              `${a.section_id}@${a.start_iso}`, a,
            ])));
            setCompletions(new Map(d.completions.map((c) => [c.task_id, c])));
          } catch {
            /* the banner already explains why decisions are unavailable */
          }
        } else {
          setApprovals(new Map());
          setCompletions(new Map());
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
          setLoading(false);
        }
      }
    })();
    return () => { cancelled = true; };
  }, [params, tick, token]);

  /* Reports are not keyed to an instance — a defect is a fact about the
     track, not about whichever month happens to be open — so they load on
     their own rather than with the plan. */
  const reloadReports = useCallback(() => {
    if (!token) { setReports([]); return; }
    getReports(token)
      .then((r) => { setReports(r.reports); setReportsError(null); })
      .catch((e: unknown) => {
        setReportsError(e instanceof Error ? e.message : String(e));
      });
  }, [token]);

  useEffect(reloadReports, [reloadReports, tick]);

  const setParams = useCallback((patch: Partial<PlanParams>) => {
    setParamsState((p) => ({ ...p, ...patch }));
  }, []);

  const isApproved = useCallback(
    (b: Block) => approvals.has(blockKey(b)), [approvals]);
  const isDone = useCallback(
    (b: Block) => b.tasks.every((t) => completions.has(t.id)), [completions]);

  const toggleApproval = useCallback(async (b: Block) => {
    if (!plan || !token) return;
    const key = blockKey(b);
    if (approvals.has(key)) {
      await apiUnapprove(plan.instance_id, b, token);
      setApprovals((m) => { const n = new Map(m); n.delete(key); return n; });
    } else {
      const rec = await apiApprove(plan.instance_id, b, token);
      setApprovals((m) => new Map(m).set(key, rec));
    }
  }, [plan, approvals, token]);

  const toggleDone = useCallback(async (b: Block) => {
    if (!plan || !token) return;
    const currentlyDone = b.tasks.every((t) => completions.has(t.id));
    const next = new Map(completions);
    for (const t of b.tasks) {
      if (currentlyDone) {
        await uncompleteJob(plan.instance_id, t.id, token);
        next.delete(t.id);
      } else {
        next.set(t.id, await completeJob(plan.instance_id, t.id, token));
      }
    }
    setCompletions(next);
  }, [plan, completions, token]);

  const value = useMemo<Ctx>(() => ({
    plan, store, approvals, completions, reports, reloadReports, reportsError,
    params, division, setDivision, loading, error,
    setParams, reload: () => setTick((t) => t + 1),
    toggleApproval, toggleDone, isApproved, isDone,
  }), [plan, store, approvals, completions, reports, reloadReports, reportsError,
    params, division, setDivision, loading, error,
    setParams, toggleApproval, toggleDone, isApproved, isDone]);

  return (
    <PlannerContext.Provider value={value}>{children}</PlannerContext.Provider>
  );
}
