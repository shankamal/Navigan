"use client";

import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import {
  Boxes,
  Building2,
  RefreshCw,
  WandSparkles,
  Workflow,
} from "lucide-react";
import "./navigan-lifecycle.css";

const capabilities = [
  {
    label: "Prepare",
    icon: Building2,
    subtitle: "Customers · Environments",
    x: 50,
    y: 7,
    planned: false,
  },
  {
    label: "Build",
    icon: Boxes,
    subtitle: "Cluster management",
    x: 81,
    y: 35,
    planned: false,
  },
  {
    label: "Transform",
    icon: WandSparkles,
    subtitle: "App transformation · Planned",
    x: 70,
    y: 75,
    planned: true,
  },
  {
    label: "Move",
    icon: Workflow,
    subtitle: "Migration · Onboarding*",
    x: 30,
    y: 75,
    planned: false,
  },
  {
    label: "Evolve",
    icon: RefreshCw,
    subtitle: "Upgrades · Planned",
    x: 19,
    y: 35,
    planned: true,
  },
];
const stageColors = ["#3284dc", "#159caa", "#a267d5", "#bd790e", "#7ba83e"];
const stageDescriptions = [
  "Prepare your cloud foundation.",
  "Build and manage with clarity.",
  "Transform applications for what’s next.",
  "Move workloads with confidence.",
  "Evolve your platform with control.",
];
const stageDetails = [
  "Register customers, connect cloud environments and review infrastructure baselines. Keep each customer’s resources within their authorized scope.",
  "Configure Kubernetes cluster requests, track provisioning and inspect platform service health. Access connected operational tools when they are ready.",
  "Planned: assess application changes needed for containers and guide modernization. Automated application transformation is a roadmap capability.",
  "Discover workloads, select migration scope and collect deployment evidence. Application onboarding, migration execution and traffic cutover are planned.",
  "Planned: assess upgrade readiness and guide version changes with compatibility checks, validation and recovery planning.",
];
// Curves follow the five-stage reference, with endpoints outside each icon.
const connectors = [
  "M 393 42 Q 463 99 555 122",
  "M 581 163 Q 535 206 521 264",
  "M 470 293 Q 357 273 250 293",
  "M 201 262 Q 193 195 157 166",
  "M 168 122 Q 266 98 327 42",
];
export const LIFECYCLE_DURATION_MS = 15_000;

/** Shared scene for the once-per-login transition and the replayable About page. */
export function NaviganLifecycle({
  autoPlay = true,
  onComplete,
}: {
  autoPlay?: boolean;
  onComplete?: () => void;
}) {
  const sceneId = useId();
  const looping = !onComplete;
  const [elapsed, setElapsed] = useState(0);
  const [running, setRunning] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  const time = useRef(0);
  const completed = useRef(false);
  const manuallyPaused = useRef(false);
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
    const duration = LIFECYCLE_DURATION_MS;
    let frame = 0;
    let last = performance.now();
    const tick = (now: number) => {
      time.current = Math.min(duration, time.current + Math.max(0, now - last));
      last = now;
      setElapsed(time.current);
      if (time.current < duration) frame = requestAnimationFrame(tick);
      else if (looping) {
        time.current = 0;
        setElapsed(0);
        frame = requestAnimationFrame(tick);
      } else {
        setRunning(false);
        setAnnouncement("Overview complete.");
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [running, reduced, looping]);

  useEffect(() => {
    if (!looping && elapsed >= LIFECYCLE_DURATION_MS && !completed.current) {
      completed.current = true;
      callback.current?.();
    }
  }, [elapsed, looping]);

  useEffect(() => {
    const visibility = () => {
      setRunning(
        !document.hidden &&
          autoPlay &&
          !completed.current &&
          !manuallyPaused.current,
      );
    };
    document.addEventListener("visibilitychange", visibility);
    return () => document.removeEventListener("visibilitychange", visibility);
  }, [autoPlay]);

  const duration = LIFECYCLE_DURATION_MS;
  const progress = Math.min(1, elapsed / duration);
  const done = reduced || progress >= 1;
  const activeIndex = Math.min(
    capabilities.length - 1,
    Math.floor(progress * capabilities.length),
  );
  const active = (i: number) => !done && i === activeIndex;
  const nodeDone = (i: number) => done || i < activeIndex;
  const moving = running && !done && !reduced;
  const botStyle = {
    "--bob": moving ? `${-2 + Math.sin(elapsed / 600) * 2}px` : "0px",
    "--tilt": moving ? `${Math.sin(elapsed / 900) * 2}deg` : "0deg",
    "--wave": moving ? `${-55 + Math.sin(elapsed / 220) * 20}deg` : "-30deg",
    "--blink": moving && elapsed % 2300 > 2160 ? ".15" : "1",
  } as CSSProperties;

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
    manuallyPaused.current = running;
    setRunning(!running);
    setAnnouncement(running ? "Overview paused." : "Overview playing.");
  }

  return (
    <div className={`navigan-lifecycle ${looping ? "nb-about" : "nb-welcome"}`}>
      <section
        className="nb-surface"
        aria-label="Navigan lifecycle overview"
        data-complete={done}
        data-moving={moving}
      >
        <div className="nb-heading">
          <h2>
            Navigan<span>.</span>
          </h2>
          <p>THE CONTAINER LIFECYCLE, CONNECTED</p>
        </div>
        <div
          className="nb-map"
          role="img"
          aria-label="Prepare, Build, Transform, Move and Evolve, with governance throughout."
        >
          <svg
            className="nb-lines"
            viewBox="0 0 720 390"
            preserveAspectRatio="none"
            aria-hidden="true"
          >
            <defs>
              {capabilities.map((c, i) => (
                <marker
                  key={c.label}
                  id={`${sceneId}-arrow-${i}`}
                  viewBox="0 0 10 10"
                  refX="8"
                  refY="5"
                  markerWidth="5"
                  markerHeight="5"
                  orient="auto-start-reverse"
                >
                  <path
                    d="M 1 1 L 9 5 L 1 9"
                    fill="none"
                    stroke={active(i) ? stageColors[i] : "#a8bdcc"}
                    strokeWidth="2"
                  />
                </marker>
              ))}
            </defs>
            {connectors.map((path, i) => (
              <path
                key={path}
                className="nb-link"
                data-active={active(i)}
                d={path}
                style={{ "--stage": stageColors[i] } as CSSProperties}
                markerEnd={`url(#${sceneId}-arrow-${i})`}
              />
            ))}
          </svg>
          <div
            className="nb-core"
            style={{ "--stage": stageColors[activeIndex] } as CSSProperties}
          >
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
            <strong>Your Navigan guide</strong>
            <small>
              GOVERNANCE
              <br />
              THROUGHOUT
            </small>
          </div>
          <div className="nb-nodes">
            {capabilities.map(({ label, icon: Icon, subtitle, x, y }, i) => {
              return (
                <div
                  key={label}
                  className="nb-node"
                  data-active={active(i)}
                  data-done={nodeDone(i)}
                  style={
                    {
                      "--stage": stageColors[i],
                      "--x": `${x}%`,
                      "--y": `${y}%`,
                    } as CSSProperties
                  }
                >
                  <span className="nb-node-icon">
                    <Icon aria-hidden="true" />
                  </span>
                  <span className="nb-node-label">
                    {label}
                    <span className="nb-subtitle">{subtitle}</span>
                  </span>
                </div>
              );
            })}
          </div>
        </div>
        <div
          className="nb-caption"
          data-stage={done ? "overview" : capabilities[activeIndex].label}
          style={{ "--stage": stageColors[activeIndex] } as CSSProperties}
        >
          <div className="nb-guide-stack">
            {capabilities.map((stage, i) => (
              <div
                key={stage.label}
                className="nb-guide-content"
                data-active={!done && activeIndex === i}
                aria-hidden={done || activeIndex !== i}
              >
                <h3 className="nb-stage-title">
                  {stageDescriptions[i]}
                  {stage.planned && (
                    <span className="nb-stage-badge">Planned</span>
                  )}
                </h3>

                {looping && (
                  <div className="nb-stage-detail">{stageDetails[i]}</div>
                )}
              </div>
            ))}
            <div
              className="nb-guide-content"
              data-active={done}
              aria-hidden={!done}
            >
              <h3 className="nb-stage-title">Your container lifecycle</h3>
              <p>Navigan. Your container lifecycle, connected.</p>
              {looping && (
                <div className="nb-stage-detail">
                  Explore customer, environment, cluster and migration
                  capabilities, with access and approvals across the platform.
                  Application transformation, onboarding and upgrades are
                  planned.
                </div>
              )}
            </div>
          </div>
        </div>
        <p className="nb-note">
          *Onboarding, app transformation and upgrades are planned. Governance
          applies throughout.
        </p>
        <footer className="nb-controls">
          {!reduced && (
            <button type="button" className="nb-play" onClick={toggle}>
              {running ? "Pause motion" : "Resume motion"}
            </button>
          )}
          <span className="nb-length">
            {reduced
              ? "Lifecycle overview"
              : looping
                ? "Continuous lifecycle overview"
                : "15-second welcome"}
          </span>
          {onComplete && (
            <button type="button" className="nb-skip" onClick={finish}>
              Skip and continue <span aria-hidden="true">→</span>
            </button>
          )}
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
