"use client";

import { useEffect, useRef } from "react";

/** A numeric coverage chart, with an accessible equivalent independent of canvas. */
export function EvidenceCoverageRing({
  value,
  total,
  label,
}: {
  value: number;
  total: number;
  label: string;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const percentage = total > 0 ? Math.round((value / total) * 100) : null;
  useEffect(() => {
    // Older browsers and test environments may not expose a canvas renderer.
    if (typeof CanvasRenderingContext2D === "undefined") return;
    const element = canvas.current;
    if (!element) return;
    const context = element.getContext("2d");
    if (!context) return;
    const scale = window.devicePixelRatio || 1;
    element.width = 88 * scale;
    element.height = 88 * scale;
    context.scale(scale, scale);
    context.lineWidth = 9;
    context.strokeStyle = "#e6eaed";
    context.beginPath();
    context.arc(44, 44, 37, 0, Math.PI * 2);
    context.stroke();
    if (total > 0 && value > 0) {
      context.strokeStyle = "#32672c";
      context.beginPath();
      context.arc(
        44,
        44,
        37,
        -Math.PI / 2,
        -Math.PI / 2 + Math.PI * 2 * Math.min(1, value / total),
      );
      context.stroke();
    }
  }, [value, total]);
  return (
    <span
      style={{
        display: "grid",
        width: 88,
        height: 88,
        flexShrink: 0,
        placeItems: "center",
      }}
      role="progressbar"
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={Math.max(1, total)}
      aria-valuetext={
        total > 0
          ? `${value} of ${total} workloads (${percentage}%)`
          : "No workloads discovered"
      }
    >
      <canvas
        ref={canvas}
        aria-hidden="true"
        width={88}
        height={88}
        style={{ width: 88, height: 88, gridArea: "1 / 1" }}
      />
      <strong aria-hidden="true" style={{ gridArea: "1 / 1", fontSize: 18 }}>
        {percentage === null ? "—" : `${percentage}%`}
      </strong>
    </span>
  );
}
