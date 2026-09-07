import { CustomerFormPage } from "@/modules/customer-management/components/customer-form";
export const metadata = { title: "Edit customer" };
export default async function EditPage({
  params,
}: {
  params: Promise<{ customerId: string }>;
}) {
  return <CustomerFormPage customerId={(await params).customerId} />;
}
