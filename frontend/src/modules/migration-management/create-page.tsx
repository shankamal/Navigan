"use client";
import { AssessmentWizard } from "./assessment-wizard";

/** Separate route entry: overview does not download the assessment wizard. */
export function MigrationCreatePage() {
  return <AssessmentWizard />;
}
