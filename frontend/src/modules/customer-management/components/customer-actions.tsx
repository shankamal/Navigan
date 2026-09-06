"use client";
import { useState, type FormEvent } from "react";
import { Button, ErrorNotice, Modal } from "@/shared/components/ui";
import { useCustomerWrite } from "../hooks/queries";
import { customersService } from "../services/customers";
import type { ActionInput, Customer, WorkflowAction } from "../model/types";
import { submissionMissing } from "../model/policy";
export function CustomerActionDialog({
  customer,
  action,
  onClose,
}: {
  customer: Customer;
  action: WorkflowAction;
  onClose: () => void;
}) {
  const [snapshot] = useState(customer);
  const [reason, setReason] = useState("");
  const [comments, setComments] = useState("");
  const [validation, setValidation] = useState("");
  const mutation = useCustomerWrite<ActionInput>(
    `${snapshot.customerId}:${action.action}`,
    (body, options) =>
      customersService.transition(
        snapshot.customerId,
        action.action,
        body,
        options,
      ),
    snapshot.version,
  );
  const missing = ["submit", "resubmit", "activate"].includes(action.action)
    ? submissionMissing(snapshot)
    : [];
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (mutation.isPending || missing.length) return;
    if (action.reasonRequired && !reason.trim()) {
      setValidation("Enter a reason to continue.");
      return;
    }
    setValidation("");
    try {
      await mutation.mutateAsync({
        ...(reason.trim() ? { reason: reason.trim() } : {}),
        ...(comments.trim() ? { comments: comments.trim() } : {}),
      });
      onClose();
    } catch {
      /* Error remains visible; identical retries retain the idempotency key. */
    }
  };
  return (
    <Modal title={action.label} onClose={onClose} busy={mutation.isPending}>
      <form onSubmit={submit}>
        <p className="muted">{snapshot.name}</p>
        <p className="action-description">
          {action.action === "deactivate"
            ? "Deactivation is terminal in this workflow. This customer will no longer be operationally available."
            : action.action === "suspend"
              ? "Suspend this customer’s operational availability. An architect can reactivate it later."
              : action.action === "reject"
                ? "Return this request to the Cloud Engineer for correction. A reason is required."
                : "This action will be recorded in the customer’s lifecycle history."}
        </p>
        {missing.length > 0 && (
          <div className="notice notice-warning">
            <strong>Complete the customer record first</strong>
            <ul>
              {missing.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}
        {mutation.isError && <ErrorNotice error={mutation.error} />}
        <fieldset disabled={mutation.isPending} className="unstyled-fieldset">
          {action.reasonRequired && (
            <label className="field">
              Reason <span aria-hidden="true">*</span>
              <textarea
                autoFocus
                value={reason}
                required
                maxLength={2000}
                rows={3}
                aria-invalid={Boolean(validation)}
                aria-describedby={
                  validation ? "action-reason-error" : undefined
                }
                onChange={(e) => setReason(e.target.value)}
              />
              {validation && (
                <span id="action-reason-error" className="field-error">
                  {validation}
                </span>
              )}
            </label>
          )}
          <label className="field">
            Comments <span className="muted">(optional)</span>
            <textarea
              value={comments}
              maxLength={2000}
              rows={3}
              onChange={(e) => setComments(e.target.value)}
            />
          </label>
        </fieldset>
        <div className="modal-actions">
          <Button
            type="button"
            variant="secondary"
            disabled={mutation.isPending}
            onClick={onClose}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            variant={action.destructive ? "danger" : "primary"}
            disabled={mutation.isPending || missing.length > 0}
          >
            {mutation.isPending ? "Saving…" : action.label}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
