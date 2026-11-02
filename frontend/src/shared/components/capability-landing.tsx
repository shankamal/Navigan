import { CircleArrowUp, PlugZap, Workflow } from "lucide-react";
import { PageHeading } from "./ui";

const capabilities = {
  transformation: {
    title: "App Transformation",
    icon: Workflow,
    description:
      "Assess and plan application modernisation for container platforms.",
    heading: "Application modernisation",
    purpose:
      "Review application readiness, identify containerisation needs and plan changes to application architecture and deployment.",
  },
  onboarding: {
    title: "Onboarding",
    icon: PlugZap,
    description:
      "Bring existing clusters and application workloads into Navigan.",
    heading: "Existing estate onboarding",
    purpose:
      "Connect existing Kubernetes clusters and workloads, associate them with the right customer and environment, and establish a governed management baseline.",
  },
  upgrades: {
    title: "Upgrades",
    icon: CircleArrowUp,
    description: "Plan and manage Kubernetes platform upgrades.",
    heading: "Platform lifecycle upgrades",
    purpose:
      "Review version compatibility and dependencies, plan cluster and add-on upgrades, and track readiness, approval and validation.",
  },
} as const;

export function CapabilityLanding({
  capability,
}: {
  capability: keyof typeof capabilities;
}) {
  const {
    title,
    icon: Icon,
    description,
    heading,
    purpose,
  } = capabilities[capability];
  return (
    <>
      <PageHeading title={title} description={description} icon={<Icon />} />
      <section className="panel" aria-label={`${title} overview`}>
        <h2>{heading}</h2>
        <p>{purpose}</p>
        <p className="muted">
          Planned capability. Workflows will be available here in a future
          release.
        </p>
      </section>
    </>
  );
}
