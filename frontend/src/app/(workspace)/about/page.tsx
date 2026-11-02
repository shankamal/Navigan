import { Info } from "lucide-react";
import { NaviganLifecycle } from "@/shared/components/navigan-lifecycle";
import { PageHeading } from "@/shared/components/ui";

export const metadata = { title: "About Navigan" };
export default function Page() {
  return (
    <>
      <PageHeading
        title="About Navigan"
        description="Explore the container management lifecycle."
        icon={<Info />}
      />
      <NaviganLifecycle />
    </>
  );
}
