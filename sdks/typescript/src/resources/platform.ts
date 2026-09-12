import { InputValidationError } from "../errors.js";
import type {
  AuditRecordList,
  PlatformFailureList,
  PlatformStatus,
  PlatformTenant,
  PlatformTenantList,
  PricingPlan,
  QuotaOverride,
  TenantStatus,
} from "../types.js";
import { Resource } from "./base.js";

const STATUSES: readonly TenantStatus[] = ["active", "suspended", "deleting", "deleted"];

/** Platform administration. Authenticates with `platformToken` (the server's `PLATFORM_ADMIN_TOKEN`). */
export class Platform extends Resource {
  async status(): Promise<PlatformStatus> {
    return this.client.request<PlatformStatus>("platform.status");
  }

  async listTenants(): Promise<PlatformTenantList> {
    return this.client.request<PlatformTenantList>("platform.list_tenants");
  }

  async getTenant(tenantId: string): Promise<PlatformTenant> {
    return this.client.request<PlatformTenant>("platform.get_tenant", { params: { tenant_id: tenantId } });
  }

  /** Change a tenant's lifecycle status. A non-active tenant cannot sign in and its credentials stop verifying. */
  async setTenantStatus(tenantId: string, status: TenantStatus): Promise<PlatformTenant> {
    if (!STATUSES.includes(status)) throw new InputValidationError(`status must be one of ${STATUSES.join(", ")}`);
    return this.client.request<PlatformTenant>("platform.set_tenant_status", { params: { tenant_id: tenantId }, json: { status } });
  }

  async listPlans(): Promise<PricingPlan[]> {
    return this.client.request<PricingPlan[]>("platform.list_plans");
  }

  /** Replace the plan limit for the given usage types. Returns the effective limits with overrides in force. */
  async setQuotaOverride(tenantId: string, overrides: Record<string, number>): Promise<QuotaOverride> {
    for (const [key, value] of Object.entries(overrides)) {
      if (!Number.isFinite(value) || value < 0) throw new InputValidationError(`override ${key} must be a non-negative number`);
    }
    return this.client.request<QuotaOverride>("platform.set_quota_override", { params: { tenant_id: tenantId }, json: { overrides } });
  }

  async listFailures(): Promise<PlatformFailureList> {
    return this.client.request<PlatformFailureList>("platform.list_failures");
  }

  async listAuditLogs(): Promise<AuditRecordList> {
    return this.client.request<AuditRecordList>("platform.list_audit_logs");
  }
}
