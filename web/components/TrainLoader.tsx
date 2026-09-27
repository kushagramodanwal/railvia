"use client";

/* The loading train.
 *
 * Drawn from the locomotive in web/lib/train-loading.svg, with three changes.
 *
 * Its palette is now tokens rather than fixed hex, so it sits correctly on a
 * paper-white page and on the dark control-room panel — a stock #248dce body
 * looked pasted on in both. Its baked-in 15%-black shading is gone for the
 * same reason: on a dark ground it read as haze.
 *
 * And it moves. The wheels turn, the rail runs beneath it, and the whole
 * engine rides very slightly on its springs. The train itself stays put and
 * the ground moves — a loading indicator that travelled would have to leave,
 * and this one has to keep waiting as long as the solve does.
 *
 * All of it stops under prefers-reduced-motion; the drawing stands still and
 * still says what it is.
 */

const WHEELS = [68.3, 195.325, 322.35];
const WHEEL_Y = 406.759;

export function TrainLoader({ label }: { label?: string }) {
  return (
    <svg className="tl" viewBox="0 0 512 512" role="img"
      aria-label={label ?? "Loading"}>
      {/* The rail, and the ground running under it. Two dashed lines at
          different rates: the near one moves faster, which reads as depth
          rather than as a single sliding stripe. */}
      <g className="tl-track">
        <line x1="-512" y1="470" x2="1024" y2="470"
          stroke="var(--text-faint)" strokeWidth="3" opacity="0.5"
          strokeDasharray="26 22" className="tl-rail" />
        <line x1="-512" y1="486" x2="1024" y2="486"
          stroke="var(--text-faint)" strokeWidth="2" opacity="0.25"
          strokeDasharray="12 30" className="tl-ballast" />
      </g>

      <g className="tl-body">
        <path fill="var(--surface-3)" d="M237.307,103.489l-23.192-35.228c-3.678-5.588-10.212-8.994-17.251-8.994H10.958 C4.906,59.267,0,63.835,0,69.471v33.651L237.307,103.489z"/> 
        <path fill="var(--primary)" d="M209.626,185.125v-81.784H22.009v233.728h379.74V194.014H218.516 C213.607,194.014,209.626,190.035,209.626,185.125z"/> 
        <rect x="291.943" y="132.524" fill="var(--surface-3)" width="81.509" height="61.49"/> 
        <path fill="var(--text-muted)" d="M384.752,104.621H280.648c-2.101,0-3.804,1.703-3.804,3.804v30.118c0,2.101,1.703,3.804,3.804,3.804 h104.104c2.101,0,3.804-1.703,3.804-3.804v-30.118C388.556,106.324,386.853,104.621,384.752,104.621z"/> 
        <g> 
        <circle fill="var(--text)" cx="68.3" cy="406.759" r="45.971"/> 
        <circle fill="var(--text)" cx="195.325" cy="406.759" r="45.971"/> 
        <circle fill="var(--text)" cx="322.35" cy="406.759" r="45.971"/> </g>
        <path fill="var(--accent)" d="M361.605,273.874h-50.362c-4.602,0-8.332-3.731-8.332-8.332s3.731-8.332,8.332-8.332h50.362 c4.602,0,8.332,3.731,8.332,8.332S366.206,273.874,361.605,273.874z"/> 
        <g> 
        <path fill="var(--text)" d="M361.605,246.183H332.7c-4.602,0-8.332-3.731-8.332-8.332s3.731-8.332,8.332-8.332h28.904 c4.602,0,8.332,3.731,8.332,8.332S366.206,246.183,361.605,246.183z"/> 
        <path fill="var(--text)" d="M430.94,351.321h-18.015c-6.173,0-11.177-5.005-11.177-11.177V190.94 c0-6.173,5.004-11.177,11.177-11.177h18.015c6.173,0,11.177,5.005,11.177,11.177v149.203 C442.118,346.316,437.114,351.321,430.94,351.321z"/> </g>
        <path fill="var(--text-faint)" d="M457.505,237.617h-15.388v55.848h15.388c3.478,0,6.299-2.82,6.299-6.299v-43.25 C463.804,240.438,460.985,237.617,457.505,237.617z"/> 
        <path fill="var(--text-muted)" d="M442.118,345.58h-40.369v57.218c0,27.578,22.357,49.934,49.934,49.934h50.711 c7.873,0,12.391-8.964,7.708-15.293L442.118,345.58z"/> 
        <path fill="var(--text)" d="M459.586,429.247c-2.581,0-5.124-1.194-6.753-3.444l-21.904-30.226 c-2.701-3.726-1.869-8.936,1.857-11.636c3.727-2.702,8.936-1.869,11.636,1.857l21.904,30.226c2.701,3.726,1.869,8.936-1.857,11.636 C462.991,428.732,461.28,429.247,459.586,429.247z"/> 
        <path fill="var(--surface-3)" d="M466.359,330.376H6.382c-3.525,0-6.382,2.857-6.382,6.382v17.644c0,3.525,2.857,6.382,6.382,6.382 h459.977c3.525,0,6.382-2.857,6.382-6.382v-17.644C472.742,333.233,469.884,330.376,466.359,330.376z"/> 
        <path fill="var(--text)" d="M161.457,142.345H70.178c-5.438,0-9.846,4.408-9.846,9.846v42.538c0,5.438,4.408,9.846,9.846,9.846 h91.279c5.438,0,9.846-4.408,9.846-9.846v-42.538C171.303,146.755,166.895,142.345,161.457,142.345z"/> 
        <path fill="var(--text-muted)" d="M232.951,117.821H7.924c-4.377,0-7.924-3.548-7.924-7.924V89.678h232.951 c4.377,0,7.924,3.548,7.924,7.924v12.294C240.877,114.273,237.328,117.821,232.951,117.821z"/> 
        <g> 
        <path fill="var(--surface-2)" d="M209.626,282.981c-4.602,0-8.332-3.731-8.332-8.332v-48.881c0-4.602,3.731-8.332,8.332-8.332 s8.332,3.731,8.332,8.332v48.881C217.958,279.251,214.228,282.981,209.626,282.981z"/> 
        <path fill="var(--surface-2)" d="M241.988,258.541c-4.602,0-8.332-3.731-8.332-8.332v-24.441c0-4.602,3.731-8.332,8.332-8.332 s8.332,3.731,8.332,8.332v24.441C250.32,254.81,246.589,258.541,241.988,258.541z"/> </g>
        <path fill="var(--surface-3)" d="M322.35,423.423H195.326c-9.203,0-16.664-7.461-16.664-16.664c0-9.203,7.461-16.664,16.664-16.664 H322.35c9.203,0,16.664,7.461,16.664,16.664C339.014,415.963,331.553,423.423,322.35,423.423z"/> 
        <path fill="var(--text-faint)" d="M195.326,423.423H68.303c-9.203,0-16.664-7.461-16.664-16.664c0-9.203,7.461-16.664,16.664-16.664 h127.023c9.203,0,16.664,7.461,16.664,16.664C211.99,415.963,204.529,423.423,195.326,423.423z"/>

        {/* Spokes. The stock wheels are plain discs — rotating one shows
            nothing at all, so each gets a cross and a crank pin to turn. */}
        {WHEELS.map((cx) => (
          <g key={cx} className="tl-wheel"
            style={{ transformOrigin: `${cx}px ${WHEEL_Y}px` }}>
            <line x1={cx - 30} y1={WHEEL_Y} x2={cx + 30} y2={WHEEL_Y}
              stroke="var(--surface)" strokeWidth="5" opacity="0.55" />
            <line x1={cx} y1={WHEEL_Y - 30} x2={cx} y2={WHEEL_Y + 30}
              stroke="var(--surface)" strokeWidth="5" opacity="0.55" />
            <circle cx={cx} cy={WHEEL_Y} r="9"
              fill="var(--surface)" opacity="0.75" />
            <circle cx={cx + 21} cy={WHEEL_Y} r="5" fill="var(--accent)" />
          </g>
        ))}
      </g>

      {/* Exhaust, off the roof, drifting back as it rises. */}
      <g className="tl-smoke" fill="var(--text-faint)">
        <circle className="tl-puff tl-puff1" cx="120" cy="60" r="13" />
        <circle className="tl-puff tl-puff2" cx="120" cy="60" r="10" />
        <circle className="tl-puff tl-puff3" cx="120" cy="60" r="7" />
      </g>
    </svg>
  );
}
