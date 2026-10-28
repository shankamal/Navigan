"use client";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowLeft,
  Building2,
  CheckCircle2,
  Circle,
  ListChecks,
  Pencil,
  Plus,
  Save,
  ShieldCheck,
  Trash2,
  Users,
} from "lucide-react";
import "./customer-form.css";
import { useAuth } from "@/shared/auth/auth-provider";
import {
  Button,
  ErrorNotice,
  Loading,
  PageHeading,
  Modal,
} from "@/shared/components/ui";
import { canCreate, canEdit, cloudProviders } from "../model/policy";
import {
  contactTypes,
  contactSchema,
  createSchema,
  updateSchema,
  type Contact,
  type Customer,
  type CreateCustomerInput,
} from "../model/types";
import { useCustomer, useCustomerWrite } from "../hooks/queries";
import { customersService } from "../services/customers";
import { ProviderPicker } from "./provider-picker";
import { ProviderMark } from "./provider-mark";
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
type ContactEditorState = {
  index: number | null;
  value: Contact;
  initial: Contact;
};
const contactLabel = (type: Contact["type"]) =>
  type[0] + type.slice(1).toLowerCase();
const normalizedContact = (contact: Contact): Contact => ({
  ...contact,
  name: contact.name.trim(),
  email: contact.email?.trim() || null,
  phone: contact.phone?.trim() || null,
});

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
  const [baseline, setBaseline] = useState(() => JSON.stringify(form));
  const [fields, setFields] = useState<Record<string, string>>({});
  const [editor, setEditor] = useState<ContactEditorState | null>(null);
  const [contactErrors, setContactErrors] = useState<Record<string, string>>(
    {},
  );
  const formRef = useRef<HTMLFormElement>(null);
  const contactNameRef = useRef<HTMLInputElement>(null);
  const editorOpen = editor !== null;
  useEffect(() => {
    if (!editorOpen) return;
    const frame = requestAnimationFrame(() => contactNameRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [editorOpen]);
  const allowNavigation = useRef(false);
  const dirty =
    JSON.stringify(form) !== baseline ||
    Boolean(
      editor && JSON.stringify(editor.value) !== JSON.stringify(editor.initial),
    );
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
  const returnUrl = customer
    ? `/customers/${customer.customerId}`
    : "/customers";
  useEffect(() => {
    if (!dirty) return;
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (allowNavigation.current) return;
      event.preventDefault();
      event.returnValue = "";
    };
    const beforeLink = (event: MouseEvent) => {
      if (
        allowNavigation.current ||
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      const link =
        event.target instanceof Element
          ? event.target.closest("a[href]")
          : null;
      if (
        !(link instanceof HTMLAnchorElement) ||
        link.target === "_blank" ||
        link.hasAttribute("download")
      )
        return;
      const destination = new URL(link.href, window.location.href);
      if (
        destination.origin === window.location.origin &&
        destination.pathname === window.location.pathname &&
        destination.search === window.location.search
      )
        return;
      if (
        !window.confirm(
          "Leave this page? Your unsaved customer changes will be lost.",
        )
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", beforeUnload);
    document.addEventListener("click", beforeLink, true);
    return () => {
      window.removeEventListener("beforeunload", beforeUnload);
      document.removeEventListener("click", beforeLink, true);
    };
  }, [dirty]);

  const openContact = (index: number | null) => {
    const value: Contact =
      index === null
        ? {
            type: form.contacts.some((c) => c.type === "PRIMARY")
              ? "TECHNICAL"
              : "PRIMARY",
            name: "",
            email: "",
            phone: "",
          }
        : { ...form.contacts[index] };
    setContactErrors({});
    setEditor({ index, value, initial: value });
  };
  const closeContact = () => {
    if (
      editor &&
      JSON.stringify(editor.value) !== JSON.stringify(editor.initial) &&
      !window.confirm("Discard the changes in this contact editor?")
    )
      return;
    setEditor(null);
    setContactErrors({});
  };
  const saveContact = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!editor) return;
    const parsed = contactSchema.safeParse(normalizedContact(editor.value));
    if (!parsed.success) {
      setContactErrors(
        Object.fromEntries(
          parsed.error.issues.map((issue) => [
            issue.path.join("."),
            issue.message,
          ]),
        ),
      );
      return;
    }
    setForm((old) => ({
      ...old,
      contacts:
        editor.index === null
          ? [...old.contacts, parsed.data]
          : old.contacts.map((value, index) =>
              index === editor.index ? parsed.data : value,
            ),
    }));
    setFields({});
    setEditor(null);
    setContactErrors({});
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (save.isPending || editor) return;
    const input = {
      name: form.name,
      description: form.description?.trim() || null,
      contacts: form.contacts.map(normalizedContact),
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
      requestAnimationFrame(() =>
        formRef.current
          ?.querySelector<HTMLElement>('[aria-invalid="true"]')
          ?.focus(),
      );
      return;
    }
    setFields({});
    try {
      const result = await save.mutateAsync({
        ...parsed.data,
        cloudProviders: form.cloudProviders,
      });
      allowNavigation.current = true;
      setBaseline(JSON.stringify(form));
      router.push(`/customers/${result.customerId}`);
    } catch {
      /* Keep all values and the existing idempotency key for a manual retry. */
    }
  };
  const primaryReady = form.contacts.some(
    (c) =>
      c.type === "PRIMARY" &&
      contactSchema.safeParse(normalizedContact(c)).success,
  );
  const checks = [
    { label: "Customer name", complete: Boolean(form.name.trim()) },
    {
      label: "At least one cloud provider",
      complete: form.cloudProviders.length > 0,
    },
    { label: "Primary contact", complete: primaryReady },
  ];
  const ready = checks.every((check) => check.complete);
  const fieldError = (key: string) =>
    fields[key] ? (
      <span className="field-error" id={`error-${key}`}>
        {fields[key]}
      </span>
    ) : null;
  return (
    <div className="customer-create-workspace">
      <header className="customer-create-heading">
        <Link className="customer-back-link" href={returnUrl}>
          <ArrowLeft size={16} aria-hidden="true" />
          {customer ? "Back to customer" : "Back to customers"}
        </Link>
        <h1>{customer ? "Edit customer" : "New customer"}</h1>
        <p>
          {customer
            ? "Update customer information and contacts."
            : "Capture the business, clouds and people in one place."}
        </p>
      </header>
      <form
        ref={formRef}
        onSubmit={submit}
        noValidate
        aria-label={customer ? "Edit customer" : "New customer"}
      >
        {save.isError && <ErrorNotice error={save.error} />}
        <div className="customer-create-columns">
          <section
            className="customer-form-panel"
            aria-labelledby="customer-profile-title"
          >
            <div className="customer-panel-heading">
              <Building2 size={30} aria-hidden="true" />
              <div>
                <h2 id="customer-profile-title">Customer profile</h2>
                <p>Add the business identity and associated cloud providers.</p>
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
              {fieldError("name")}
            </label>
            <label className="field">
              Description <span className="customer-optional">(optional)</span>
              <textarea
                value={form.description ?? ""}
                maxLength={2000}
                rows={3}
                onChange={(e) =>
                  setForm((old) => ({ ...old, description: e.target.value }))
                }
                disabled={save.isPending}
                placeholder="Add a short description of the customer"
                aria-describedby="customer-description-count"
              />
              {fieldError("description")}
              <span className="field-hint" id="customer-description-count">
                {form.description?.length ?? 0}/2,000 characters
              </span>
            </label>
            <div className="customer-cloud-section">
              <h3>Cloud providers</h3>
              <p>Select the providers associated with this customer.</p>
              {customer ? (
                <p className="customer-provider-note">
                  Manage cloud providers separately on the customer details
                  page.
                </p>
              ) : (
                <ProviderPicker
                  appearance="customer-form"
                  value={form.cloudProviders}
                  onChange={(codes) =>
                    setForm((old) => ({ ...old, cloudProviders: codes }))
                  }
                  disabled={save.isPending}
                />
              )}
            </div>
          </section>
          <section
            className="customer-form-panel"
            aria-labelledby="customer-contacts-title"
          >
            <div className="customer-panel-heading customer-contact-heading">
              <Users size={30} aria-hidden="true" />
              <div>
                <h2 id="customer-contacts-title">Contacts</h2>
                <p>Add the people responsible for this customer.</p>
              </div>
              <Button
                type="button"
                variant="secondary"
                disabled={save.isPending || form.contacts.length >= 100}
                onClick={() => openContact(null)}
              >
                <Plus size={18} aria-hidden="true" />
                Add contact
              </Button>
            </div>
            {form.contacts.length ? (
              <ul className="customer-contact-list" aria-label="Added contacts">
                {form.contacts.map((contact, index) => (
                  <li key={index}>
                    <span
                      className="customer-contact-avatar"
                      aria-hidden="true"
                    >
                      {contact.name
                        .trim()
                        .split(/\s+/)
                        .slice(0, 2)
                        .map((part) => part[0])
                        .join("")
                        .toUpperCase() || "?"}
                    </span>
                    <div className="customer-contact-copy">
                      <span>{contactLabel(contact.type)}</span>
                      <strong>{contact.name}</strong>
                      {contact.email && <span>{contact.email}</span>}
                      {contact.phone && <span>{contact.phone}</span>}
                      {Object.keys(fields).some((key) =>
                        key.startsWith(`contacts.${index}.`),
                      ) && (
                        <span className="field-error">
                          Edit this contact to correct its details.
                        </span>
                      )}
                    </div>
                    <div className="customer-contact-actions">
                      <Button
                        type="button"
                        variant="ghost"
                        aria-label={`Edit contact ${contact.name}`}
                        disabled={save.isPending}
                        onClick={() => openContact(index)}
                      >
                        <Pencil size={18} aria-hidden="true" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        aria-label={`Remove contact ${contact.name}`}
                        disabled={save.isPending}
                        onClick={() => {
                          setForm((old) => ({
                            ...old,
                            contacts: old.contacts.filter(
                              (_, i) => i !== index,
                            ),
                          }));
                          setFields({});
                        }}
                      >
                        <Trash2 size={18} aria-hidden="true" />
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="customer-contact-empty">
                <Users size={30} aria-hidden="true" />
                <strong>No contacts added yet</strong>
                <p>
                  Add a primary contact before submitting for review. You can
                  save a draft without contacts.
                </p>
              </div>
            )}
            <section
              className="customer-readiness"
              aria-labelledby="customer-readiness-title"
            >
              <div className="customer-panel-heading">
                <ShieldCheck size={30} aria-hidden="true" />
                <div>
                  <h2 id="customer-readiness-title">Customer readiness</h2>
                  <p role="status">
                    {ready
                      ? "Complete for review."
                      : !form.name.trim()
                        ? "Add a customer name to save your draft."
                        : "Draft can be saved. Complete the checklist before review."}
                  </p>
                </div>
              </div>
              <div className="customer-readiness-columns">
                <div>
                  <h3>Selected cloud providers</h3>
                  {form.cloudProviders.length ? (
                    <ul
                      className="customer-selected-providers"
                      aria-label="Selected cloud providers"
                    >
                      {form.cloudProviders.map((code) => {
                        const provider = cloudProviders.find(
                          (p) => p.code === code,
                        );
                        return (
                          <li key={code}>
                            <ProviderMark code={code} />
                            <div>
                              <strong>{provider?.shortName ?? code}</strong>
                              <span>{provider?.name ?? code}</span>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <p className="customer-provider-note">
                      No cloud providers selected yet.
                    </p>
                  )}
                </div>
                <div className="customer-completion">
                  <h3>
                    <ListChecks size={21} aria-hidden="true" />
                    Completion checklist
                  </h3>
                  <ul aria-label="Completion checklist">
                    {checks.map((check) => (
                      <li key={check.label}>
                        {check.complete ? (
                          <CheckCircle2
                            size={21}
                            className="customer-check-complete"
                            aria-hidden="true"
                          />
                        ) : (
                          <Circle
                            size={21}
                            className="customer-check-pending"
                            aria-hidden="true"
                          />
                        )}
                        <span>
                          {check.label}
                          <span className="sr-only">
                            {check.complete ? ": Complete" : ": Pending"}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
              <p className="customer-review-note">
                Save a draft, then submit for review from customer details.
              </p>
            </section>
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
          </section>
        </div>
        <div className="customer-save-bar">
          <span aria-live="polite">
            {save.isPending
              ? "Saving customer…"
              : dirty
                ? "Unsaved changes"
                : ""}
          </span>
          <div>
            <Link
              href={returnUrl}
              className={`button button-secondary ${save.isPending ? "disabled-link" : ""}`}
              aria-disabled={save.isPending}
              onClick={(event) => {
                if (save.isPending) event.preventDefault();
              }}
            >
              Cancel
            </Link>
            <Button type="submit" disabled={save.isPending}>
              <Save size={18} aria-hidden="true" />
              {save.isPending
                ? "Saving…"
                : customer
                  ? "Save changes"
                  : "Save as draft"}
            </Button>
          </div>
        </div>
      </form>
      {editor && (
        <Modal
          title={editor.index === null ? "Add contact" : "Edit contact"}
          onClose={closeContact}
        >
          <form
            className="customer-contact-editor"
            onSubmit={saveContact}
            noValidate
          >
            <p className="muted">
              Add a contact to this draft. Email and phone are optional.
            </p>
            <label className="field">
              Contact type
              <select
                value={editor.value.type}
                onChange={(e) =>
                  setEditor({
                    ...editor,
                    value: {
                      ...editor.value,
                      type: e.target.value as Contact["type"],
                    },
                  })
                }
              >
                {contactTypes.map((type) => (
                  <option key={type} value={type}>
                    {contactLabel(type)}
                  </option>
                ))}
              </select>
            </label>
            {(
              [
                {
                  key: "name",
                  label: "Full name",
                  required: true,
                  type: "text",
                  max: 255,
                },
                {
                  key: "email",
                  label: "Email (optional)",
                  required: false,
                  type: "email",
                  max: 255,
                },
                {
                  key: "phone",
                  label: "Phone (optional)",
                  required: false,
                  type: "tel",
                  max: 50,
                },
              ] as const
            ).map((item) => (
              <label key={item.key} className="field">
                {item.label}
                {item.required && <span aria-hidden="true"> *</span>}
                <input
                  ref={item.key === "name" ? contactNameRef : undefined}
                  required={item.required}
                  type={item.type}
                  maxLength={item.max}
                  value={editor.value[item.key] ?? ""}
                  aria-invalid={Boolean(contactErrors[item.key])}
                  aria-describedby={
                    contactErrors[item.key]
                      ? `contact-error-${item.key}`
                      : undefined
                  }
                  onChange={(e) =>
                    setEditor({
                      ...editor,
                      value: { ...editor.value, [item.key]: e.target.value },
                    })
                  }
                />
                {contactErrors[item.key] && (
                  <span
                    className="field-error"
                    id={`contact-error-${item.key}`}
                    role="alert"
                  >
                    {contactErrors[item.key]}
                  </span>
                )}
              </label>
            ))}
            <div className="modal-actions">
              <Button type="button" variant="secondary" onClick={closeContact}>
                Cancel
              </Button>
              <Button type="submit">
                {editor.index === null ? "Add to customer" : "Update contact"}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  );
}
