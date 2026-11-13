"use client";

import {
  CheckCircle2,
  PackageCheck,
  ServerCog,
  ShieldCheck,
} from "lucide-react";

export function PatchingWorkspace() {
  return (
    <section className="upgrade-patching-workspace" aria-label="Patching">
      <p className="upgrade-section-help upgrade-patching-intro-copy">
        Same-version node, AMI and security remediation is managed separately
        from Kubernetes minor-version upgrades.
      </p>

      <div className="upgrade-patch-intro">
        <article>
          <ServerCog aria-hidden="true" />
          <div>
            <strong>Managed node / AMI patch</strong>
            <p>
              Patch EKS managed node groups to a newer EKS-optimized AMI while
              keeping the Kubernetes minor version unchanged.
            </p>
          </div>
        </article>
        <article>
          <ShieldCheck aria-hidden="true" />
          <div>
            <strong>Security and runtime patch</strong>
            <p>
              Track operating-system, kernel and container-runtime remediation
              separately from control-plane version upgrades.
            </p>
          </div>
        </article>
        <article>
          <PackageCheck aria-hidden="true" />
          <div>
            <strong>Full upgrade relationship</strong>
            <p>
              A full cluster upgrade can absorb the applicable managed-node AMI
              refresh for the target Kubernetes version. Independent patching is
              used when the Kubernetes version stays the same.
            </p>
          </div>
        </article>
      </div>

      <div className="upgrade-patch-boundary">
        <CheckCircle2 aria-hidden="true" />
        <div>
          <strong>UI foundation ready</strong>
          <p>
            Patch inventory and patch-plan execution will be connected in the
            next implementation step. No unsupported patch action is exposed
            from this screen.
          </p>
        </div>
      </div>
    </section>
  );
}
