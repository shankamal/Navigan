"use client";
import { useId, useState } from "react";
import { Button } from "@/shared/components/ui";
import type { ConfigurationSchema, JsonValue } from "../model/types";
export function cleanConfiguration(value: JsonValue): JsonValue {
  if (Array.isArray(value))
    return value
      .map(cleanConfiguration)
      .filter(
        (v) =>
          v !== "" &&
          v !== null &&
          (typeof v !== "object" || Object.keys(v).length > 0),
      );
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .map(([k, v]) => [k, cleanConfiguration(v)])
        .filter(
          ([, v]) =>
            v !== "" &&
            v !== null &&
            (typeof v !== "object" || Object.keys(v).length > 0),
        ),
    );
  return value;
}
function JsonField({
  title,
  value,
  onChange,
}: {
  title: string;
  value: JsonValue;
  onChange: (value: JsonValue) => void;
}) {
  const [text, setText] = useState(JSON.stringify(value ?? {}, null, 2));
  const [error, setError] = useState("");
  return (
    <label className="field">
      {title}
      <textarea
        rows={5}
        value={text}
        aria-invalid={!!error}
        onChange={(e) => {
          setText(e.target.value);
          try {
            const parsed: unknown = JSON.parse(e.target.value);
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
              throw Error();
            onChange(parsed as JsonValue);
            setError("");
            e.target.setCustomValidity("");
          } catch {
            setError("Enter a valid JSON object.");
            e.target.setCustomValidity("Enter a valid JSON object.");
          }
        }}
      />
      {error && <span role="alert">{error}</span>}
      <span className="muted">
        Infrastructure references only. Never enter credentials.
      </span>
    </label>
  );
}
export function ConfigurationFields({
  schema,
  value,
  onChange,
  path = "configuration",
  required = false,
}: {
  schema: ConfigurationSchema;
  value: JsonValue | undefined;
  onChange: (v: JsonValue) => void;
  path?: string;
  required?: boolean;
}) {
  const id = useId();
  const title = schema.title || path.split(".").at(-1) || "Value";
  if (schema.const) return null;
  if (schema.type === "object") {
    const object =
      value && typeof value === "object" && !Array.isArray(value) ? value : {};
    const properties = schema.properties || {};
    if (!Object.keys(properties).length)
      return <JsonField title={title} value={object} onChange={onChange} />;
    return (
      <fieldset className="environment-fieldset">
        <legend>{title}</legend>
        <div className="form-grid">
          {Object.entries(properties).map(([key, child]) => (
            <ConfigurationFields
              key={key}
              schema={child}
              value={object[key]}
              path={`${path}.${key}`}
              required={schema.required?.includes(key)}
              onChange={(next) => onChange({ ...object, [key]: next })}
            />
          ))}
        </div>
      </fieldset>
    );
  }
  if (schema.type === "array") {
    const items = Array.isArray(value) ? value : [];
    return (
      <fieldset className="environment-fieldset">
        <legend>
          {title}
          {required ? " *" : ""}
        </legend>
        {items.map((item, index) => (
          <div className="environment-array-item" key={index}>
            <ConfigurationFields
              schema={schema.items!}
              value={item}
              path={`${path}.${index}`}
              onChange={(next) =>
                onChange(items.map((v, i) => (i === index ? next : v)))
              }
            />
            <Button
              type="button"
              variant="ghost"
              aria-label={`Remove ${title} ${index + 1}`}
              onClick={() => onChange(items.filter((_, i) => i !== index))}
            >
              Remove
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="secondary"
          disabled={items.length >= 100}
          onClick={() =>
            onChange([...items, schema.items?.type === "object" ? {} : ""])
          }
        >
          Add {title.toLowerCase()}
        </Button>
        {required && (
          <small className="muted">
            Required for submission
            {schema.minItems ? `: at least ${schema.minItems}` : ""}.
          </small>
        )}
      </fieldset>
    );
  }
  return (
    <label className="field" htmlFor={id}>
      {title}
      {required ? " *" : ""}
      {schema.enum ? (
        <select
          id={id}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">Select…</option>
          {schema.enum.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
      ) : schema.type === "boolean" ? (
        <input
          id={id}
          type="checkbox"
          checked={value === true}
          onChange={(e) => onChange(e.target.checked)}
        />
      ) : (
        <input
          id={id}
          value={
            typeof value === "string" || typeof value === "number" ? value : ""
          }
          onChange={(e) => onChange(e.target.value)}
          maxLength={1024}
        />
      )}
    </label>
  );
}
