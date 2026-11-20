import { useEffect, useState } from "react";
import { meta } from "../api";
import type { ProductMeta } from "../api/types";

let cached: Promise<ProductMeta | null> | null = null;

/** Product version and environment, fetched once per page load. `null` until known or if unavailable. */
export function useMeta(): ProductMeta | null {
  const [value, setValue] = useState<ProductMeta | null>(null);
  useEffect(() => {
    let live = true;
    cached ??= meta.get().catch(() => {
      cached = null;
      return null;
    });
    void cached.then((result) => { if (live) setValue(result); });
    return () => { live = false; };
  }, []);
  return value;
}

/** Test hook: forget the cached response. */
export function resetMetaCache(): void {
  cached = null;
}
