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
