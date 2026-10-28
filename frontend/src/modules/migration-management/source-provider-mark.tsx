import { Github, Layers } from "lucide-react";
import styles from "./migration-experience.module.css";
export function SourceProviderMark({
  provider,
}: {
  provider: "github" | "aws" | "docker" | "helm" | "kubernetes";
}) {
  return (
    <span
      className={styles.providerMark}
      data-provider={provider}
      aria-hidden="true"
    >
      {provider === "github" ? (
        <Github size={18} />
      ) : provider === "helm" ? (
        <Layers size={18} />
      ) : (
        <img
          src={`/logos/${provider === "aws" ? "amazonwebservices" : provider}.svg`}
          alt=""
        />
      )}
    </span>
  );
}
