import type { Subscription as SubscriptionModel, UsageDimension, UsageSummary, UsageType } from "../types.js";
import { Resource } from "./base.js";

export class Subscription extends Resource {
  /** `GET /v1/subscription` (rate-limited per credential). */
  async get(): Promise<SubscriptionModel> {
    return this.client.request<SubscriptionModel>("subscription.get");
  }
}

export class Usage extends Resource {
  /** `GET /v1/usage`: nine dimensions for the current period. */
  async get(): Promise<UsageSummary> {
    return this.client.request<UsageSummary>("usage.get");
  }

  /** One dimension of the current usage, or `undefined` if the server omits it. */
  async dimension(type: UsageType): Promise<UsageDimension | undefined> {
    const summary = await this.get();
    return summary.dimensions.find((d) => d.type === type);
  }
}
