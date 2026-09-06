import { CustomerDetailsView } from "@/modules/customer-management/components/customer-details";
export const metadata = { title: "Customer details" };
export default async function CustomerPage({
  params,
}: {
  params: Promise<{ customerId: string }>;
}) {
  return <CustomerDetailsView customerId={(await params).customerId} />;
}
