import { TrainLoader } from "@/components/TrainLoader";

/* Shown while the planner segment loads.
 *
 * This is the gap between clicking "Open the planner" on the landing page and
 * the app appearing — the one wait on that journey that had nothing in it.
 * Next renders this boundary automatically for anything under (app), so every
 * route behind the sign-in gets it without asking.
 */
export default function AppLoading() {
  return (
    <div className="tl-wrap tl-route">
      <TrainLoader label="Opening the planner" />
      <div className="tl-say">Opening the planner…</div>
    </div>
  );
}
