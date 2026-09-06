"use client";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Plus, Save, Trash2 } from "lucide-react";
import { useAuth } from "@/shared/auth/auth-provider";
import {
  Button,
  ErrorNotice,
  Loading,
  PageHeading,
} from "@/shared/components/ui";
import { canCreate, canEdit } from "../model/policy";
import {
  contactTypes,
  createSchema,
  updateSchema,
  type Contact,
  type Customer,
  type CreateCustomerInput,
} from "../model/types";
import { useCustomer, useCustomerWrite } from "../hooks/queries";
import { customersService } from "../services/customers";
import { ProviderPicker } from "./provider-picker";
export function CustomerFormPage({ customerId }: { customerId?: string }) {
  const { identity } = useAuth();
  const query = useCustomer(customerId ?? "");
  const [revision, setRevision] = useState(0);
  if (customerId && query.isPending)
    return <Loading label="Loading customer details…" />;
  if (customerId && query.isError)
    return (
      <ErrorNotice error={query.error} onRetry={() => void query.refetch()} />
    );
  const customer = customerId ? query.data : undefined;
  const allowed = customer ? canEdit(identity, customer) : canCreate(identity);
  if (!allowed)
    return (
      <>
        <PageHeading title="Customer editing unavailable" />
        <p className="muted">
          Only a Cloud Engineer can edit a draft or rejected customer. Creating
          customers also requires onboarding access.
        </p>
        <Link
          href={customer ? `/customers/${customer.customerId}` : "/customers"}
          className="button button-secondary"
        >
          Back to customers
        </Link>
      </>
    );
  return (
    <CustomerForm
      key={revision}
      customer={customer}
      onReload={async () => {
        await query.refetch();
        setRevision((old) => old + 1);
      }}
    />
  );
}
export function CustomerForm({
  customer,
  onReload,
}: {
  customer?: Customer;
  onReload?: () => Promise<void>;
}) {
  const router = useRouter();
  const [version] = useState(customer?.version);
  const [form, setForm] = useState<CreateCustomerInput>({
    name: customer?.name ?? "",
    description: customer?.description ?? "",
    contacts: customer?.contacts ?? [],
    cloudProviders: customer?.cloudProviders ?? [],
  });
  const [fields, setFields] = useState<Record<string, string>>({});
  const save = useCustomerWrite<CreateCustomerInput>(
    customer ? `update:${customer.customerId}` : "create",
    (input, options) =>
      customer
        ? customersService.update(
            customer.customerId,
            {
              name: input.name,
              description: input.description,
              contacts: input.contacts,
            },
            options,
          )
        : customersService.create(input, options),
    version,
  );
  const updateContact = (index: number, patch: Partial<Contact>) =>
    setForm((old) => ({
      ...old,
      contacts: old.contacts.map((contact, i) =>
        i === index ? { ...contact, ...patch } : contact,
      ),
    }));
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (save.isPending) return;
    const input = {
      name: form.name,
      description: form.description?.trim() || null,
      contacts: form.contacts.map((c) => ({
        ...c,
        email: c.email?.trim() || null,
        phone: c.phone?.trim() || null,
      })),
    };
    const parsed = customer
      ? updateSchema.safeParse(input)
      : createSchema.safeParse({
          ...input,
          cloudProviders: form.cloudProviders,
        });
    if (!parsed.success) {
      setFields(
        Object.fromEntries(
          parsed.error.issues.map((issue) => [
            issue.path.join("."),
            issue.message,
          ]),
        ),
      );
      return;
    }
    setFields({});
    try {
      const result = await save.mutateAsync({
        ...parsed.data,
        cloudProviders: form.cloudProviders,
      });
      router.push(`/customers/${result.customerId}`);
    } catch {
      /* Keep form and idempotency key for a manual retry. */
    }
  };
  const errorText = (key: string) =>
    fields[key] ? (
      <span className="field-error" id={`error-${key}`}>
        {fields[key]}
      </span>
    ) : null;
  return (
    <>
      <Link
        className="back-link"
        href={customer ? `/customers/${customer.customerId}` : "/customers"}
      >
        <ArrowLeft size={16} />
        {customer ? "Back to customer" : "Back to customers"}
      </Link>
      <PageHeading
        eyebrow="CUSTOMER MANAGEMENT"
        title={customer ? "Edit customer" : "Create customer"}
        description={
          customer
            ? "Update customer information and contacts."
            : "Start with a draft. You can complete the details before submitting for review."
        }
      />
      <form onSubmit={submit} noValidate className="form-layout">
        <div className="form-main">
          {save.isError && <ErrorNotice error={save.error} />}
          <section className="panel form-section">
            <div className="section-heading">
              <span className="section-number">01</span>
              <div>
                <h2>Customer information</h2>
                <p className="muted">
                  The business identity for this customer.
                </p>
              </div>
            </div>
            <label className="field">
              Customer name <span aria-hidden="true">*</span>
              <input
                autoComplete="organization"
                value={form.name}
                maxLength={255}
                required
                aria-invalid={Boolean(fields.name)}
                aria-describedby={fields.name ? "error-name" : undefined}
                onChange={(e) =>
                  setForm((old) => ({ ...old, name: e.target.value }))
                }
                disabled={save.isPending}
                placeholder="Enter the legal or business name"
              />
              {errorText("name")}
            </label>
            <label className="field">
              Description
              <textarea
                value={form.description ?? ""}
                maxLength={2000}
                rows={4}
                onChange={(e) =>
                  setForm((old) => ({ ...old, description: e.target.value }))
                }
                disabled={save.isPending}
                placeholder="Add a short description of the customer"
              />
              {errorText("description")}
              <span className="field-hint">
                {form.description?.length ?? 0}/2,000 characters
              </span>
            </label>
          </section>
          {!customer && (
            <section className="panel form-section">
              <div className="section-heading">
                <span className="section-number">02</span>
                <div>
                  <h2>Cloud providers</h2>
                  <p className="muted">
                    Select the providers associated with this customer.
                  </p>
                </div>
              </div>
              <ProviderPicker
                value={form.cloudProviders}
                onChange={(codes) =>
                  setForm((old) => ({ ...old, cloudProviders: codes }))
                }
                disabled={save.isPending}
              />
              <p className="field-hint">
                You’ll need at least one provider before submitting for review.
              </p>
            </section>
          )}
          <section className="panel form-section">
            <div className="section-heading">
              <span className="section-number">{customer ? "02" : "03"}</span>
              <div>
                <h2>Contacts</h2>
                <p className="muted">
                  Add the people responsible for this customer.
                </p>
              </div>
            </div>
            {form.contacts.length === 0 && (
              <p className="muted contact-empty">
                No contacts added yet. A primary contact is required before
                submission.
              </p>
            )}
            {form.contacts.map((contact, index) => (
              <fieldset
                key={index}
                className="contact-form"
                disabled={save.isPending}
              >
                <legend>Contact {index + 1}</legend>
                <div className="contact-form-heading">
                  <strong>
                    {contact.type === "PRIMARY"
                      ? "Primary contact"
                      : "Additional contact"}
                  </strong>
                  <Button
                    type="button"
                    variant="ghost"
                    aria-label={`Remove contact ${index + 1}`}
                    onClick={() =>
                      setForm((old) => ({
                        ...old,
                        contacts: old.contacts.filter((_, i) => i !== index),
                      }))
                    }
                  >
                    <Trash2 size={17} />
                    Remove
                  </Button>
                </div>
                <div className="two-column">
                  <label className="field">
                    Contact type
                    <select
                      value={contact.type}
                      onChange={(e) =>
                        updateContact(index, {
                          type: e.target.value as Contact["type"],
                        })
                      }
                    >
                      {contactTypes.map((type) => (
                        <option key={type} value={type}>
                          {type.charAt(0) + type.slice(1).toLowerCase()}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    Full name <span aria-hidden="true">*</span>
                    <input
                      value={contact.name}
                      required
                      maxLength={255}
                      aria-invalid={Boolean(fields[`contacts.${index}.name`])}
                      aria-describedby={
                        fields[`contacts.${index}.name`]
                          ? `error-contacts.${index}.name`
                          : undefined
                      }
                      onChange={(e) =>
                        updateContact(index, { name: e.target.value })
                      }
                    />
                    {errorText(`contacts.${index}.name`)}
                  </label>
                  <label className="field">
                    Email
                    <input
                      value={contact.email ?? ""}
                      type="email"
                      maxLength={255}
                      aria-invalid={Boolean(fields[`contacts.${index}.email`])}
                      aria-describedby={
                        fields[`contacts.${index}.email`]
                          ? `error-contacts.${index}.email`
                          : undefined
                      }
                      onChange={(e) =>
                        updateContact(index, { email: e.target.value })
                      }
                    />
                    {errorText(`contacts.${index}.email`)}
                  </label>
                  <label className="field">
                    Phone
                    <input
                      value={contact.phone ?? ""}
                      type="tel"
                      maxLength={50}
                      onChange={(e) =>
                        updateContact(index, { phone: e.target.value })
                      }
                    />
                    {errorText(`contacts.${index}.phone`)}
                  </label>
                </div>
              </fieldset>
            ))}
            <Button
              type="button"
              variant="secondary"
              disabled={save.isPending || form.contacts.length >= 100}
              onClick={() =>
                setForm((old) => ({
                  ...old,
                  contacts: [
                    ...old.contacts,
                    {
                      type: old.contacts.length ? "TECHNICAL" : "PRIMARY",
                      name: "",
                      email: "",
                      phone: "",
                    },
                  ],
                }))
              }
            >
              <Plus size={17} />
              Add contact
            </Button>
          </section>
          <div className="form-actions">
            <Link
              href={
                customer ? `/customers/${customer.customerId}` : "/customers"
              }
              className={`button button-secondary ${save.isPending ? "disabled-link" : ""}`}
              aria-disabled={save.isPending}
              onClick={(event) => {
                if (save.isPending) event.preventDefault();
              }}
            >
              Cancel
            </Link>
            <Button type="submit" disabled={save.isPending}>
              <Save size={17} />
              {save.isPending
                ? "Saving…"
                : customer
                  ? "Save changes"
                  : "Save as draft"}
            </Button>
          </div>
        </div>
        <aside className="form-aside">
          <span className="eyebrow">ONBOARDING CHECKLIST</span>
          <h2>Ready for review</h2>
          <ul className="checklist">
            <li className={form.name.trim() ? "complete" : ""}>
              Customer name
            </li>
            <li className={form.cloudProviders.length ? "complete" : ""}>
              At least one cloud provider
            </li>
            <li
              className={
                form.contacts.some((c) => c.type === "PRIMARY" && c.name.trim())
                  ? "complete"
                  : ""
              }
            >
              Primary contact
            </li>
          </ul>
          <p className="muted">
            Save a draft at any time. Submit the completed record from the
            customer details page.
          </p>
          {customer && (
            <p className="muted">
              Manage cloud providers separately on the customer details page.
            </p>
          )}
          {customer && version !== customer.version && (
            <div className="notice">
              A newer version is available. Reload before saving again.
            </div>
          )}
          {customer && save.isError && onReload && (
            <Button
              type="button"
              variant="secondary"
              disabled={save.isPending}
              onClick={() => {
                if (
                  window.confirm(
                    "Discard your unsaved edits and load the latest customer record?",
                  )
                )
                  void onReload();
              }}
            >
              Reload latest record
            </Button>
          )}
        </aside>
      </form>
    </>
  );
}
