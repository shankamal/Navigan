import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import {
  MaintenanceCalendar,
  calendarDays,
  dayKey,
} from "../src/modules/upgrade-management/maintenance-calendar";
import { clusterAccount } from "../src/modules/upgrade-management/cluster-context";
import type {
  Cluster,
  EksUpgradePlan,
} from "../src/modules/cluster-management/model";
vi.mock("@/shared/auth/auth-provider", () => ({
  useAuth: () => ({ identity: { subject: "viewer" } }),
}));
describe("maintenance calendar and cluster context", () => {
  it("starts weeks on Monday and crosses a year boundary without losing dates", () => {
    const days = calendarDays(new Date(2027, 0, 1));
    expect(days).toHaveLength(42);
    expect(days[0].getDay()).toBe(1);
    expect(dayKey(days[0])).toBe("2026-12-28");
    expect(days.filter((d) => d.getMonth() === 0)).toHaveLength(31);
  });
  it("uses only verified twelve-digit account values", () => {
    expect(
      clusterAccount({
        provisioningRoleArn: "arn:aws:iam::123456789012:role/Provisioning",
      }),
    ).toBe("123456789012");
    expect(clusterAccount({ configuration: { awsAccountId: "fake" } })).toBe(
      "Not reported",
    );
  });
  it("selects a day, shows an overdue request, and opens its exact plan", () => {
    const now = new Date(2026, 10, 7, 12),
      date = new Date(2026, 10, 7, 8),
      review = vi.fn();
    const cluster = {
      clusterId: "CLU-test",
      clusterName: "demo",
      customerName: "DB Schenker",
      environmentName: "Production",
      provisioningRoleArn: "arn:aws:iam::123456789012:role/Provisioning",
    } as Cluster;
    const plan = {
      planId: "UPG-test",
      kind: "CONTAINER",
      status: "SUBMITTED",
      scheduledFor: date.toISOString(),
      currentVersion: "1.36",
      targetVersion: "1.37",
    } as EksUpgradePlan;
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MaintenanceCalendar
          rows={[{ clusterName: "demo", cluster, plan }]}
          now={now.getTime()}
          onReview={review}
        />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/Overdue · inactive/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review plan" }));
    expect(review).toHaveBeenCalledWith("UPG-test");
    fireEvent.click(screen.getByRole("button", { name: "Next month" }));
    expect(
      screen.getByRole("heading", { name: "December 2026" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/No maintenance starts/)).toBeInTheDocument();
  });
});

it("offers container and utility requests for a selected future date, with no actions on past dates", () => {
  const onCreate = vi.fn(),
    now = new Date(2026, 10, 7, 12);
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MaintenanceCalendar
        rows={[]}
        onReview={vi.fn()}
        now={now.getTime()}
        canCreate
        onCreate={onCreate}
      />
    </QueryClientProvider>,
  );
  expect(
    screen.getByRole("button", { name: "Create upgrade on 2026-11-06" }),
  ).toBeDisabled();
  fireEvent.click(
    screen.getByRole("button", { name: "Create upgrade on 2026-11-10" }),
  );
  const dialog = screen.getByRole("dialog", {
    name: /New maintenance request/,
  });
  expect(dialog).toHaveFocus();
  fireEvent.click(screen.getByRole("button", { name: "Cluster upgrade" }));
  expect(onCreate).toHaveBeenCalledWith("containers", "2026-11-10");
  fireEvent.click(screen.getByRole("button", { name: "Utility upgrade" }));
  expect(onCreate).toHaveBeenCalledWith("utilities", "2026-11-10");
  fireEvent.keyDown(dialog, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("shows a Monday-based week, opens entries directly and filters requested starts", () => {
  const review = vi.fn(),
    now = new Date(2026, 10, 11, 12);
  const cluster = {
    clusterId: "CLU-week",
    clusterName: "Weekly cluster",
    customerId: "CUS-one",
    customerName: "Db Schenker",
    environmentId: "ENV-one",
    environmentName: "DEV",
  } as Cluster;
  const plan = {
    planId: "UPG-week",
    kind: "UTILITY",
    utilityEvidence: { label: "Headlamp" },
    status: "SUBMITTED",
    scheduledFor: new Date(2026, 10, 12, 22).toISOString(),
    currentVersion: "0.45.0",
    targetVersion: "0.46.0",
  } as EksUpgradePlan;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MaintenanceCalendar
        rows={[{ clusterName: cluster.clusterName, cluster, plan }]}
        now={now.getTime()}
        onReview={review}
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Week" }));
  expect(
    screen.getByRole("heading", {
      name:
        "Week of " +
        new Date(2026, 10, 9).toLocaleDateString(undefined, {
          day: "numeric",
          month: "long",
          year: "numeric",
        }),
    }),
  ).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Weekly cluster/ }));
  expect(review).toHaveBeenCalledWith("UPG-week");
  fireEvent.change(screen.getByLabelText("Calendar status"), {
    target: { value: "Scheduled" },
  });
  expect(
    screen.queryByRole("button", { name: /Weekly cluster/ }),
  ).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Next week" }));
  expect(
    screen.getByRole("heading", {
      name:
        "Week of " +
        new Date(2026, 10, 16).toLocaleDateString(undefined, {
          day: "numeric",
          month: "long",
          year: "numeric",
        }),
    }),
  ).toBeInTheDocument();
});

it("shows each multi-step maintenance start and opens the parent plan", () => {
  const now = new Date(2027, 0, 1, 8),
    review = vi.fn();
  const cluster = {
    clusterId: "CLU-step",
    clusterName: "demo",
    customerName: "DB Schenker",
    environmentName: "Prod",
    provisioningRoleArn: "arn:aws:iam::123456789012:role/Provisioning",
  } as Cluster;
  const plan = {
    planId: "UPG-path",
    kind: "CONTAINER",
    status: "SCHEDULED",
    scheduledFor: new Date(2027, 0, 1, 10).toISOString(),
    currentVersion: "1.34",
    targetVersion: "1.36",
    execution: {},
    planSpec: {
      scope: "CLUSTER",
      steps: [1, 2].map((day) => ({
        fromVersion: `1.${33 + day}`,
        targetVersion: `1.${34 + day}`,
        window: {
          scheduledFor: new Date(2027, 0, day, 10).toISOString(),
          durationMinutes: 120,
        },
        operations: [
          {
            kind: "CONTROL_PLANE",
            name: "demo",
            from: `1.${33 + day}`,
            to: `1.${34 + day}`,
          },
        ],
      })),
    },
  } as EksUpgradePlan;
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MaintenanceCalendar
        rows={[{ clusterName: "demo", cluster, plan }]}
        now={now.getTime()}
        onReview={review}
      />
    </QueryClientProvider>,
  );
  expect(screen.getAllByText(/demo · Step 1/).length).toBeGreaterThan(0);
  expect(screen.getAllByText(/demo · Step 2/).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByRole("button", { name: "Review plan" }));
  expect(review).toHaveBeenCalledWith("UPG-path");
});
