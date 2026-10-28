import { Cloud } from "lucide-react";
const marks: Record<string, string> = {
  AWS: "amazonwebservices",
  AZURE: "microsoftazure",
  GCP: "googlecloud",
  OCI: "oracle",
};
export function ProviderMark({ code }: { code: string }) {
  return marks[code] ? (
    <img
      className="customer-provider-mark"
      src={`/logos/${marks[code]}.svg`}
      width={44}
      height={36}
      alt=""
      aria-hidden="true"
    />
  ) : (
    <Cloud size={32} aria-hidden="true" />
  );
}
