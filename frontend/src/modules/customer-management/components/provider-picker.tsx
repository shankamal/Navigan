"use client";
import { Check, Cloud } from "lucide-react";
import { cloudProviders } from "../model/policy";
export function ProviderPicker({
  value,
  onChange,
  disabled = false,
}: {
  value: string[];
  onChange: (codes: string[]) => void;
  disabled?: boolean;
}) {
  const options = [
    ...cloudProviders,
    ...value
      .filter((code) => !cloudProviders.some((p) => p.code === code))
      .map((code) => ({ code, name: code, shortName: code })),
  ];
  return (
    <fieldset disabled={disabled} className="provider-picker">
      <legend className="sr-only">Associated cloud providers</legend>
      {options.map((provider) => (
        <label
          key={provider.code}
          className={`provider-option ${value.includes(provider.code) ? "checked" : ""}`}
        >
          <input
            type="checkbox"
            checked={value.includes(provider.code)}
            onChange={(event) =>
              onChange(
                event.target.checked
                  ? [...value, provider.code]
                  : value.filter((code) => code !== provider.code),
              )
            }
          />
          <Cloud size={23} aria-hidden="true" />
          <span>
            <strong>{provider.shortName}</strong>
            <small>{provider.name}</small>
          </span>
          <span className="checkbox-visual" aria-hidden="true">
            {value.includes(provider.code) && <Check size={14} />}
          </span>
        </label>
      ))}
    </fieldset>
  );
}
