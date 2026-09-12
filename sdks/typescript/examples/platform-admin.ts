/**
 * Platform operations: tenants, plans, quota overrides, failures and audit.
 *
 * The /v1/platform routes authenticate with the server's PLATFORM_ADMIN_TOKEN
 * (set it in .env; an empty value disables the routes).
 *
 *   export PLATFORM_ADMIN_TOKEN=...
 *   npm run build && node examples/platform-admin.ts [tenant-id-to-grant-extra-events]
 */
import { GraphRec } from "@graphrec/sdk";

const when = (iso: string) => iso.slice(0, 16).replace("T", " ");

async function main(tenantId: string | undefined): Promise<void> {
  const token = process.env.PLATFORM_ADMIN_TOKEN;
  if (!token) throw new Error("PLATFORM_ADMIN_TOKEN is not set");
  const ops = new GraphRec({ platformToken: token, baseUrl: process.env.GRAPHREC_BASE_URL, useEnv: false });

  console.log("platform:", await ops.platform.status());

  for (const plan of await ops.platform.listPlans()) console.log(`plan ${plan.code.padEnd(6)} ${JSON.stringify(plan.limits)}`);

  const tenants = (await ops.platform.listTenants()).items;
  const suspended = tenants.filter((t) => t.status === "suspended");
  console.log(`${tenants.length} tenants, ${suspended.length} suspended`);

  if (tenantId) {
    const quota = await ops.platform.setQuotaOverride(tenantId, { accepted_events: 1_000_000 });
    console.log("effective limits:", quota.limits, "overrides:", quota.overrides);
  }

  for (const failure of (await ops.platform.listFailures()).items.slice(0, 10)) {
    console.log(`${when(failure.occurred_at)} ${failure.severity.padEnd(7)} ${failure.event_type}`);
  }
  for (const record of (await ops.platform.listAuditLogs()).items.slice(0, 10)) {
    console.log(`${when(record.occurred_at)} ${record.action_type} -> ${record.outcome}`);
  }
}

main(process.argv[2]).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
