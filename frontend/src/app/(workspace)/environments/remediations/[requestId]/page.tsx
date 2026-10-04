import { BootstrapRemediationDetails } from "@/modules/environment-management/components/bootstrap-remediation-admin";

export const metadata = { title: "Bootstrap Remediation Review" };

export default async function Page({
  params,
}: {
  params: Promise<{ requestId: string }>;
}) {
  const { requestId } = await params;
  return <BootstrapRemediationDetails requestId={requestId} />;
}
