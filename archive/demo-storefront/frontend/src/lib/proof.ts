/**
 * Honest wording for recommendation provenance.
 *
 * Only `proofStatus` (computed by the storefront server from configuration and the
 * upstream response) drives user-facing claims. "For Maya" / "Model-backed" appear
 * only when the status is `model_verified`; the raw strategy string is shown solely
 * in the technical disclosure, labelled as raw.
 */
import type { ProofStatus, Provenance } from "./types";

export type ProofTone = "verified" | "preview" | "fallback";

export function proofTone(status: ProofStatus): ProofTone {
  if (status === "model_verified") return "verified";
  if (status === "catalog_fallback") return "fallback";
  return "preview";
}

export function proofColor(status: ProofStatus): string {
  return { verified: "var(--verified)", preview: "var(--preview)", fallback: "var(--ink-2)" }[proofTone(status)];
}

export function proofIcon(status: ProofStatus): string {
  return { verified: "✓", preview: "!", fallback: "◇" }[proofTone(status)];
}

export function proofPillLabel(status: ProofStatus): string {
  return { verified: "Verified personalization", preview: "Serving preview · unverified", fallback: "Catalog fallback" }[proofTone(status)];
}

/** Heading over a shelf. Never claims personalisation unless verified. */
export function shelfHeading(status: ProofStatus | null, personaName: string, variant: "home" | "related" | "continue" = "home"): string {
  if (status === "model_verified") return variant === "home" ? `For ${personaName}` : variant === "related" ? "You may also like" : "Continue exploring";
  if (status === "catalog_fallback") return variant === "home" ? "From the catalog" : variant === "related" ? "More from the catalog" : "Continue exploring";
  return variant === "home" ? "Recommended" : variant === "related" ? "You may also like" : "Continue exploring";
}

export function provenanceLine(prov: Provenance | null, personaName: string, isGuest: boolean): string {
  if (!prov) return "Waiting for GraphRec…";
  const version = prov.modelVersionId ? ` · version ${prov.modelVersionId.slice(0, 8)}` : "";
  switch (prov.proofStatus) {
    case "model_verified":
      return `Model-backed for ${personaName}${version}`;
    case "catalog_fallback":
      return isGuest ? "Catalog fallback · new visitor, no history" : `Catalog fallback · showing as ${personaName}`;
    default:
      return `GraphRec serving preview${version} · showing as ${personaName}`;
  }
}

export function proofExplainer(status: ProofStatus): string {
  switch (status) {
    case "model_verified":
      return "Rankings are user-specific, repeat exactly, and this model version passed the verification script.";
    case "catalog_fallback":
      return "GraphRec answered from the catalog (newest active products), not from a model. Labelled as a fallback.";
    default:
      return "The serving path is live and returns a model version, but the query is not yet user-specific. Not presented as personalization.";
  }
}

/** Rows for the "Why am I seeing this?" disclosure. */
export function whyRows(prov: Provenance): { label: string; value: string }[] {
  return [
    { label: "Request ID", value: prov.requestId },
    { label: "Raw strategy (backend)", value: prov.rawStrategy },
    { label: "Fallback", value: String(prov.fallbackUsed) + (prov.fallbackUsed ? ` (${prov.fallbackTier})` : "") },
    { label: "Model version", value: prov.modelVersionId ?? "n/a" },
    { label: "Proof status", value: prov.proofStatus },
    { label: "Excluded products", value: String(prov.excludedCount) },
    { label: "Returned but not shown", value: String(prov.omittedProductCount) },
    { label: "Impression event", value: prov.impressionEventId ?? "—" },
  ];
}
