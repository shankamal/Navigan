"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  ArrowRightLeft,
  Boxes,
  Building2,
  CircleArrowUp,
  Layers3,
  Network,
  PlugZap,
  ShieldCheck,
  Workflow,
} from "lucide-react";
import { runtimeConfig } from "@/shared/config/runtime-config";
import "./navigan-lifecycle.css";

const capabilities = [
  { label: "Customers", icon: Building2 },
  { label: "Environments", icon: Layers3 },
  { label: "Clusters", icon: Network },
  { label: "Migration", icon: ArrowRightLeft },
  { label: "App Transformation", icon: Workflow, planned: true },
  { label: "Onboarding", icon: PlugZap, planned: true },
  { label: "Upgrades", icon: CircleArrowUp, planned: true },
  { label: "Governance", icon: ShieldCheck },
];
const phases = [
  { nodes: [0, 1], copy: "Set up customers and cloud environments." },
  { nodes: [2, 3], copy: "Manage clusters and plan workload migration." },
  {
    nodes: [4, 5, 6],
    copy: "Next: transform applications, onboard and upgrade.",
  },
  { nodes: [7], copy: "Govern the lifecycle. Bring it together with Navigan." },
];
export const LIFECYCLE_DURATION_MS = 11_200;

/** Shared scene for the once-per-login transition and the replayable About page. */
export function NaviganLifecycle({
  autoPlay = false,
  onComplete,
}: {
  autoPlay?: boolean;
  onComplete?: () => void;
}) {
  const [elapsed, setElapsed] = useState(0);
  const [running, setRunning] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const time = useRef(0);
  const completed = useRef(false);
  const callback = useRef(onComplete);
  useEffect(() => {
    callback.current = onComplete;
  }, [onComplete]);

  useEffect(() => {
    const query = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const applyPreference = () => {
      const reduce = query?.matches ?? false;
      setReduced(reduce);
      if (reduce) {
        time.current = LIFECYCLE_DURATION_MS;
        setElapsed(LIFECYCLE_DURATION_MS);
        setRunning(false);
      }
    };
    applyPreference();
    if (!query?.matches) setRunning(autoPlay);
    query?.addEventListener("change", applyPreference);
    return () => query?.removeEventListener("change", applyPreference);
  }, [autoPlay]);

  useEffect(() => {
    if (!running || reduced) return;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      time.current = Math.min(
        LIFECYCLE_DURATION_MS,
        time.current + Math.max(0, now - last),
      );
      last = now;
      setElapsed(time.current);
      if (time.current < LIFECYCLE_DURATION_MS)
        frame = requestAnimationFrame(tick);
      else {
        setRunning(false);
        setAnnouncement("Overview complete.");
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [running, reduced]);

  useEffect(() => {
    if (elapsed >= LIFECYCLE_DURATION_MS && !completed.current) {
      completed.current = true;
      callback.current?.();
    }
  }, [elapsed]);

  useEffect(() => {
    const pause = () => {
      if (document.hidden) {
        setRunning(false);
        setAnnouncement("Overview paused.");
      }
    };
    document.addEventListener("visibilitychange", pause);
    return () => document.removeEventListener("visibilitychange", pause);
  }, []);

  const progress = Math.min(1, elapsed / LIFECYCLE_DURATION_MS);
  const done = progress >= 1;
  const phaseIndex = Math.min(3, Math.floor(progress * 4));
  const phase = phases[phaseIndex];
  const active = (i: number) => elapsed > 0 && !done && phase.nodes.includes(i);
  const nodeDone = (i: number) =>
    done || phases.slice(0, phaseIndex).some((p) => p.nodes.includes(i));
  const moving = running && !done && !reduced;
  const botStyle = {
    "--bob": moving ? `${-2 + Math.sin(elapsed / 230) * 2}px` : "0px",
    "--tilt": moving ? `${Math.sin(elapsed / 460) * 3}deg` : "0deg",
    "--wave": moving ? `${-55 + Math.sin(elapsed / 220) * 20}deg` : "-30deg",
    "--blink": moving && elapsed % 2300 > 2160 ? ".15" : "1",
  } as CSSProperties;
  const logo = runtimeConfig().corporateLogoUrl;
  function finish() {
    time.current = LIFECYCLE_DURATION_MS;
    setElapsed(LIFECYCLE_DURATION_MS);
    setRunning(false);
    setAnnouncement("Overview complete.");
  }
  function toggle() {
    if (reduced) {
      finish();
      return;
    }
    if (done) {
      time.current = 0;
      setElapsed(0);
      completed.current = false;
    }
    setRunning(!running);
    setAnnouncement(running ? "Overview paused." : "Overview playing.");
  }

  return (
    <div className="navigan-lifecycle">
      <section
        className="nb-surface"
        aria-label="Navigan lifecycle overview"
        data-complete={done}
      >
        <header className="nb-header">
          {logo ? (
            <img className="nb-logo" src={logo} alt="Corporate logo" />
          ) : (
            <span className="nb-brand">
              Deloitte<em>.</em>
            </span>
          )}
          <span className="nb-product">Container Management Platform</span>
        </header>
        <div className="nb-heading">
          <span className="nb-eyebrow">
            {onComplete ? "WELCOME TO NAVIGAN" : "ABOUT NAVIGAN"}
          </span>
          <h2>One platform. Every stage.</h2>
        </div>
        <div
          className="nb-map"
          role="img"
          aria-label="Navigan bot guides the connected circular lifecycle: customers, environments, clusters, migration, planned app transformation, onboarding and upgrades, and governance."
        >
          <svg className="nb-lines" viewBox="0 0 430 430" aria-hidden="true">
            <g>
              {capabilities.map((c, i) => {
                const angle = ((i * 45 - 90) * Math.PI) / 180;
                return (
                  <line
                    key={c.label}
                    className="nb-spoke"
                    data-active={active(i)}
                    x1="215"
                    y1="215"
                    x2={215 + 146.2 * Math.cos(angle)}
                    y2={215 + 146.2 * Math.sin(angle)}
                  />
                );
              })}
            </g>
            <circle className="nb-ring" cx="215" cy="215" r="146.2" />
            <circle
              className="nb-arc"
              cx="215"
              cy="215"
              r="146.2"
              pathLength="1"
              style={{ strokeDashoffset: 1 - progress }}
            />
          </svg>
          <div className="nb-core">
            <div className="nb-bot" style={botStyle} aria-hidden="true">
              <div className="nb-antenna" />
              <div className="nb-head">
                <div className="nb-face">
                  <span className="nb-eye" />
                  <span className="nb-eye" />
                </div>
              </div>
              <div className="nb-arm" />
              <div className="nb-arm nb-arm-right" />
              <div className="nb-body">
                <Boxes />
              </div>
            </div>
            <strong>Navigan</strong>
            <small>CONNECTED LIFECYCLE</small>
          </div>
          <div className="nb-nodes">
            {capabilities.map(({ label, icon: Icon, planned }, i) => {
              const angle = ((i * 45 - 90) * Math.PI) / 180;
              return (
                <div
                  key={label}
                  className="nb-node"
                  data-active={active(i)}
                  data-done={nodeDone(i)}
                  style={
                    {
                      "--x": `${50 + 34 * Math.cos(angle)}%`,
                      "--y": `${50 + 34 * Math.sin(angle)}%`,
                    } as CSSProperties
                  }
                >
                  <span className="nb-node-icon">
                    <Icon aria-hidden="true" />
                  </span>
                  <span>{label}</span>
                  {planned && <span className="nb-planned">Planned</span>}
                </div>
              );
            })}
          </div>
        </div>
        <div className="nb-caption">
          <span className="nb-caption-label">YOUR PLATFORM GUIDE</span>
          <p>
            {done
              ? "Navigan. Your container lifecycle, connected."
              : elapsed
                ? phase.copy
                : "Your container lifecycle, connected in one platform."}
          </p>
        </div>
        <p className="nb-note">
          App Transformation, Onboarding and Upgrades are planned capabilities.
        </p>
        <footer className="nb-controls">
          {!reduced && (
            <button type="button" className="nb-play" onClick={toggle}>
              {done
                ? "Replay animation"
                : running
                  ? "Pause"
                  : elapsed
                    ? "Resume"
                    : "Play animation"}
            </button>
          )}
          <span className="nb-length">
            {reduced ? "Lifecycle overview" : "11-second overview"}
          </span>
          <button type="button" className="nb-skip" onClick={finish}>
            {onComplete ? "Skip and continue" : "Show overview"}{" "}
            <span aria-hidden="true">→</span>
          </button>
        </footer>
        <div className="nb-time" aria-hidden="true">
          <span style={{ width: `${progress * 100}%` }} />
        </div>
        <span className="nb-status" role="status" aria-live="polite">
          {announcement}
        </span>
      </section>
    </div>
  );
}
