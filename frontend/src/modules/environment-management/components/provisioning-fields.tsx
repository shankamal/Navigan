"use client";
import { ConfigurationFields } from "./configuration-fields";
import type { ConfigurationSchema, JsonValue } from "../model/types";

export function ProvisioningFields({
  schema,
  configuration,
  onChange,
}: {
  schema: ConfigurationSchema;
  configuration: Record<string, JsonValue>;
  onChange: (configuration: Record<string, JsonValue>) => void;
}) {
  const clusterSchema = schema.properties?.cluster;
  const provisioningSchema = schema.properties?.provisioning;
  if (!clusterSchema || !provisioningSchema) return null;
  return (
    <section className="panel panel-padding environment-provisioning">
      <h2>Provisioning</h2>
      <p className="muted">
        Kubernetes version, node groups and the Navigan provisioning role used
        to create the cluster with Terraform. This is separate from the AWS
        Discovery role above: discovery only reads AWS inventory and is never
        stored, while these settings are saved with this environment and
        copied into every Cluster Setup request created against it.
      </p>
      <ConfigurationFields
        schema={clusterSchema}
        value={configuration.cluster}
        path="configuration.cluster"
        required
        onChange={(next) => onChange({ ...configuration, cluster: next })}
      />
      <ConfigurationFields
        schema={provisioningSchema}
        value={configuration.provisioning}
        path="configuration.provisioning"
        required
        onChange={(next) => onChange({ ...configuration, provisioning: next })}
      />
    </section>
  );
}
