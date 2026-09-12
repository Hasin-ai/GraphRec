/**
 * Register a tenant, activate its administrator with the setup token and mint a storefront API key.
 *
 *   npm run build && node examples/tenant-onboarding.ts "Acme Outfitters" owner@acme.example 'a-long-password'
 */
import { GraphRec, STOREFRONT_KEY_SCOPES } from "@graphrec/sdk";

async function main(businessName: string, adminEmail: string, password: string): Promise<void> {
  const publicClient = new GraphRec({ useEnv: false, baseUrl: process.env.GRAPHREC_BASE_URL });
  const tenant = await publicClient.tenants.register({ name: businessName, admin_email: adminEmail });
  console.log(`tenant ${tenant.id} (${tenant.status}) - next step: ${tenant.next_step}`);
  if (tenant.setup_token === null) {
    throw new Error(
      "This registration was already submitted, so its one-time setup token is not returned again. " +
        `Issue a new one with: docker compose exec api python -m scripts.issue_account_setup_token ${adminEmail}`,
    );
  }
  await publicClient.auth.setupPassword({ setupToken: tenant.setup_token, password, email: adminEmail });

  // The admin client logs in on demand and renews its 15-minute token automatically.
  const admin = publicClient.withCredentials({ email: adminEmail, password });
  const plan = await admin.subscription.get();
  console.log(`plan=${plan.plan_code} limits=${JSON.stringify(plan.limits)}`);

  const key = await admin.apiKeys.create({ name: "storefront-backend", scopes: STOREFRONT_KEY_SCOPES });
  console.log("Store this secret now - it is shown only once:");
  console.log(`  GRAPHREC_API_KEY=${key.secret}`);

  const usage = await admin.usage.get();
  for (const dimension of usage.dimensions) {
    const limit = dimension.limit === null ? "unlimited" : dimension.limit;
    console.log(`  ${dimension.type.padEnd(26)} ${dimension.used} / ${limit} ${dimension.unit}`);
  }
}

const [businessName, adminEmail, password] = process.argv.slice(2);
if (!businessName || !adminEmail || !password) {
  console.error('usage: node examples/tenant-onboarding.ts "Business name" admin@example.com password');
  process.exit(2);
}
main(businessName, adminEmail, password).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
