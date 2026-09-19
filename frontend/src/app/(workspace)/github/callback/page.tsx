"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { clusters } from "@/modules/cluster-management/service";
import { ErrorNotice, Loading, PageHeading } from "@/shared/components/ui";

export default function GitHubAppCallbackPage() {
  const router = useRouter();
  const parameters = useSearchParams();
  const [error, setError] = useState<unknown>();

  useEffect(() => {
    const pending = sessionStorage.getItem("navigan.github.authorization");
    const state = parameters.get("state");
    const installationId = Number(parameters.get("installation_id"));
    if (!pending || !state || !Number.isSafeInteger(installationId)) {
      setError(new Error("The GitHub authorization session is incomplete."));
      return;
    }
    const request = JSON.parse(pending) as {
      clusterId: string;
      version: number;
      state: string;
    };
    if (request.state !== state) {
      setError(new Error("The GitHub authorization state does not match."));
      return;
    }
    clusters
      .completeGitHubAuthorization(
        request.clusterId,
        request.version,
        state,
        installationId,
      )
      .then(() => {
        sessionStorage.removeItem("navigan.github.authorization");
        router.replace(`/clusters/${request.clusterId}`);
      })
      .catch(setError);
  }, [parameters, router]);

  return (
    <>
      <PageHeading
        eyebrow="GITHUB ORGANIZATION"
        title="Completing authorization"
        description="Navigan is verifying the GitHub App installation and organization."
      />
      {error ? <ErrorNotice error={error} /> : <Loading label="Verifying GitHub organization…" />}
    </>
  );
}
