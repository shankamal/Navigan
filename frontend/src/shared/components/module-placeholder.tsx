import Link from "next/link";
import { Construction, ArrowLeft } from "lucide-react";
import { PageHeading, EmptyState } from "./ui";
export function ModulePlaceholder({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <>
      <PageHeading eyebrow="PLATFORM MODULE" title={title} />
      <section className="panel">
        <EmptyState
          icon={<Construction size={30} />}
          title="This module is planned"
          action={
            <Link href="/customers" className="button button-secondary">
              <ArrowLeft size={16} />
              Back to customers
            </Link>
          }
        >
          {description} Customer Management is available now.
        </EmptyState>
      </section>
    </>
  );
}
