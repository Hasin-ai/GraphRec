import type { ReactNode } from "react";
import { blobStyle, tileStyle } from "../lib/format";

/** CSS-generated product art: a category gradient with a soft tinted circle. */
export function Tile({ id, category, accent, dim, children, className = "" }: { id: string; category: string; accent?: string | null; dim?: boolean; children?: ReactNode; className?: string }) {
  return (
    <div className={`fct-tile ${dim ? "dim" : ""} ${className}`} style={tileStyle(id, category, accent)} role="img" aria-label={`${category} product art`}>
      <span aria-hidden="true" className="fct-blob" style={blobStyle(id, category)} />
      {children}
    </div>
  );
}

export function Skeleton({ style, className = "" }: { style?: React.CSSProperties; className?: string }) {
  return <div className={`fct-skel ${className}`} style={style} aria-hidden="true" />;
}

export function CardSkeleton() {
  return (
    <div>
      <Skeleton style={{ aspectRatio: "4 / 5", borderRadius: "var(--radius-lg)" }} />
      <Skeleton style={{ height: 12, width: "70%", borderRadius: 999, marginTop: 12 }} />
      <Skeleton style={{ height: 12, width: "38%", borderRadius: 999, marginTop: 8 }} />
    </div>
  );
}
