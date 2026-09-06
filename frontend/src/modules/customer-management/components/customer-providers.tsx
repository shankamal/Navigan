"use client";
import { useState } from "react";
import { Pencil } from "lucide-react";
import { Button, ErrorNotice, Loading, Modal } from "@/shared/components/ui";
import { useCustomerProviders, useCustomerWrite } from "../hooks/queries";
import { customersService } from "../services/customers";
import { ProviderPicker } from "./provider-picker";
import { ProviderBadges } from "./customer-badges";
export function CustomerProviders({
  customerId,
  editable,
}: {
  customerId: string;
  editable: boolean;
}) {
  const query = useCustomerProviders(customerId);
  const [editing, setEditing] = useState(false);
  return (
    <section className="panel form-section">
      <div className="panel-title">
        <h2>Cloud providers</h2>
        {editable && query.data && (
          <Button variant="ghost" onClick={() => setEditing(true)}>
            <Pencil size={16} />
            Manage providers
          </Button>
        )}
      </div>
      {query.isPending ? (
        <Loading label="Loading cloud providers…" />
      ) : query.isError ? (
        <ErrorNotice error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <ProviderBadges codes={query.data.cloudProviders} />
          <p className="field-hint">
            Customer-level associations. Accounts, regions, and clusters belong
            to other modules.
          </p>
          {editing && (
            <ProviderDialog
              customerId={customerId}
              initialCodes={query.data.cloudProviders}
              version={query.data.version}
              onClose={() => setEditing(false)}
            />
          )}
        </>
      )}
    </section>
  );
}
function ProviderDialog({
  customerId,
  initialCodes,
  version,
  onClose,
}: {
  customerId: string;
  initialCodes: string[];
  version: number;
  onClose: () => void;
}) {
  const [codes, setCodes] = useState(initialCodes);
  const [snapshotVersion] = useState(version);
  const mutation = useCustomerWrite<string[]>(
    `${customerId}:providers`,
    (input, options) =>
      customersService.replaceProviders(customerId, input, options),
    snapshotVersion,
  );
  return (
    <Modal
      title="Manage cloud providers"
      onClose={onClose}
      busy={mutation.isPending}
    >
      <p className="muted">
        Select providers for this customer. At least one is required before
        submission.
      </p>
      {mutation.isError && <ErrorNotice error={mutation.error} />}
      <ProviderPicker
        value={codes}
        onChange={setCodes}
        disabled={mutation.isPending}
      />
      <div className="modal-actions">
        <Button
          variant="secondary"
          disabled={mutation.isPending}
          onClick={onClose}
        >
          Cancel
        </Button>
        <Button
          disabled={mutation.isPending}
          onClick={() => {
            void mutation
              .mutateAsync(codes)
              .then(onClose)
              .catch(() => {});
          }}
        >
          {mutation.isPending ? "Saving…" : "Save providers"}
        </Button>
      </div>
    </Modal>
  );
}
