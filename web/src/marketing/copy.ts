/**
 * Brand copy shared by the marketing hero and the auth showcase, so the two can
 * never drift. Plain, specific, technical; no exclamation marks.
 */
export const BRAND = {
  name: "GraphRec",
  tagline: "Recommendations that learn from every interaction.",
  lede: "Sync your catalog, stream events, and serve time-aware graph recommendations from one multi-tenant console.",
  /** The hero's longer lede: the auth lede plus what makes the results trustworthy. */
  heroLede: "Sync your catalog, stream shopper events, and train a time-aware graph model on your own history. GraphRec serves real-time Top-N recommendations from one multi-tenant console, and every result records the model and rules that produced it.",
  pillars: [
    "Train and version models on your own event history",
    "Promote, roll back and monitor serving deployments",
    "Scoped API keys and per-tenant usage quotas",
  ],
  /** One line for the footer and the meta description. */
  description: "A multi-tenant recommendation platform for e-commerce: catalog sync, event streaming, time-aware graph models and real-time Top-N recommendations.",
} as const;

/** "GraphRec: Recommendations that learn from every interaction" — the landing page and index.html title. */
export const HOME_TITLE = `${BRAND.name}: ${BRAND.tagline.replace(/\.$/, "")}`;
