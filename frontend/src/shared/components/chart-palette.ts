/** Shared chart contract. Provider identity, lifecycle and health are separate semantics. */
export const chartColors = {
  ready: "#6D957B",
  active: "#6D957B",
  draft: "#9AA6B2",
  pending: "#C4A064",
  review: "#7A8998",
  running: "#7096B2",
  blocked: "#C96863",
  paused: "#D9DEE3",
  unknown: "#7A8998",
  remainder: "#D9DEE3",
  track: "#E8ECF0",
  purple: "#9B8BAE",
  teal: "#72A2A0",
};
export const cloudColors = ["#E5A044", "#4D8FC7", "#63A477", "#C96863"];
export const lifecycleColors = [
  chartColors.active,
  chartColors.draft,
  chartColors.pending,
  chartColors.review,
  chartColors.remainder,
];
export const healthColors = [
  chartColors.ready,
  chartColors.pending,
  chartColors.paused,
  chartColors.unknown,
];
export const categoryColors = [
  chartColors.running,
  chartColors.active,
  chartColors.purple,
  chartColors.pending,
  chartColors.teal,
  chartColors.blocked,
];
