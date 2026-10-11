import { useEffect, useState } from "react";
import { meta } from "../api";
import { mergeLivePlans, type MarketingPlan } from "./plans";

/** Live plan limits from `GET /v1/plans`; seeded defaults (flagged `live: false`) until then. */
export function useLivePlans(): { plans: MarketingPlan[]; live: boolean } {
  const [state, setState] = useState(() => mergeLivePlans(null));
  useEffect(() => {
    let active = true;
    meta.plans().then(
      (result) => { if (active) setState(mergeLivePlans(result.items)); },
      () => { /* keep seeded defaults; the page says they are not live */ },
    );
    return () => { active = false; };
  }, []);
  return state;
}
