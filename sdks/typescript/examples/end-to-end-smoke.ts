/**
 * End-to-end smoke test against a running GraphRec stack (docker compose up).
 *
 * Creates a throw-away tenant and walks every major SDK area. Run it after
 * changing the API or the SDK:
 *
 *   npm run smoke -- --base-url http://localhost:8010
 *   PLATFORM_ADMIN_TOKEN=... npm run smoke     # also exercises client.platform
 */
import { randomUUID } from "node:crypto";
import { AuthenticationError, GraphRec, PermissionDeniedError, STOREFRONT_KEY_SCOPES, type ProductInput } from "@graphrec/sdk";
import { CatalogSync, EventTracker, RecommendationSession } from "@graphrec/sdk/ecommerce";

function step(title: string): void {
  console.log(`\n== ${title}`);
}

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`SMOKE TEST FAILED: ${message}`);
}

function argument(flag: string, fallback: string | undefined): string | undefined {
  const index = process.argv.indexOf(flag);
  return index === -1 ? fallback : process.argv[index + 1];
}

async function main(baseUrl: string, platformToken: string | undefined): Promise<void> {
  const suffix = randomUUID().replace(/-/g, "").slice(0, 8);
  const email = `smoke-${suffix}@example.org`;
  const password = `smoke-password-${suffix}`;
  const publicClient = new GraphRec({ baseUrl, useEnv: false });

  step("health");
  console.log(await publicClient.health());

  step("register tenant");
  const tenant = await publicClient.tenants.register({ name: `SDK Smoke ${suffix}`, admin_email: email });
  console.log(tenant.id, tenant.status);
  assert(tenant.setup_token, "registration must return a one-time setup token");
  await publicClient.auth.setupPassword({ setupToken: tenant.setup_token, password, email });

  step("setup token is single-use");
  const reuse = await publicClient.auth.setupPassword({ setupToken: tenant.setup_token, password: "another-password" }).then(
    () => null,
    (error: unknown) => error,
  );
  assert(reuse instanceof AuthenticationError && reuse.code === "invalid_setup_token", "a used setup token was accepted");
  console.log("reused token rejected:", reuse.code);

  const admin = publicClient.withCredentials({ email, password });
  step("subscription & usage");
  console.log((await admin.subscription.get()).plan_code, (await admin.usage.get()).dimensions.length, "usage dimensions");

  step("API key lifecycle");
  const key = await admin.apiKeys.create({ name: `smoke-${suffix}`, scopes: STOREFRONT_KEY_SCOPES });
  const rotated = await admin.apiKeys.rotate(key.id, { reason: "smoke test", gracePeriodSeconds: 60 });
  assert(rotated.secret !== key.secret, "rotation must issue a new secret");
  console.log((await admin.apiKeys.list()).items.map((k) => k.prefix));

  const store = publicClient.withCredentials({ apiKey: rotated.secret });
  step("catalog");
  const catalog: ProductInput[] = Array.from({ length: 60 }, (_, i) => ({ external_id: `sku-${i}`, title: `Product ${i}`, price: `${10 + i}.00`, category: ["shirts", "shoes"][i % 2] }));
  console.log((await new CatalogSync(store).run(catalog)).summary());
  await store.products.update("sku-1", { price: "9.99" });
  await store.products.disable("sku-59");

  step("events");
  const tracker = new EventTracker(store, { batchSize: 25 });
  for (let i = 0; i < 120; i += 1) {
    const user = `user-${i % 12}`;
    tracker.view(user, `sku-${i % 60}`);
    if (i % 5 === 0) tracker.purchase(user, `sku-${i % 60}`, { orderId: `ORD-${i}` });
  }
  await tracker.close();
  console.log((await store.events.listBatches()).map((b) => b.accepted_count).slice(0, 5));

  step("scope enforcement");
  const denied = await store.modelVersions.list().then(
    () => null,
    (error: unknown) => error,
  );
  assert(denied instanceof PermissionDeniedError, "a storefront key without models:read listed model versions");
  console.log("storefront key cannot read the model registry:", denied.code);

  step("dataset upload & snapshot");
  const csv = "event_id,event_type,user_id,external_product_id\n" + Array.from({ length: 50 }, (_, i) => `csv-${suffix}-${i},click,user-${i % 7},sku-${i % 30}\n`).join("");
  const upload = await admin.datasets.upload(csv, { filename: `events-${suffix}.csv` });
  console.log("uploaded", upload.accepted_events, "events; snapshot", upload.dataset_snapshot.checksum.slice(0, 12));
  const snapshot = await admin.datasets.createSnapshot({ cutoffAt: new Date() });

  step("training & activation");
  let job = await admin.trainingJobs.create({ dataset_snapshot_id: snapshot.id });
  job = await admin.trainingJobs.wait(job.id, { timeoutMs: 300_000, pollIntervalMs: 2_000 });
  assert(job.model_version_id !== null, `training job ${job.id} finished ${job.status} without a model version`);
  const version = await admin.modelVersions.activate(job.model_version_id);
  console.log(version.version_tag, version.status, (await admin.deployment.get()).status);
  console.log("p95", (await admin.metrics.summary()).p95_latency_ms, "ms");

  step("recommendations & feedback");
  const widget = new RecommendationSession(store);
  const recs = await widget.recommend({ userId: "user-1", topN: 5, excludeProductIds: ["sku-0"] });
  const ids = recs.items.map((i) => i.external_product_id);
  assert(!ids.includes("sku-0") && !ids.includes("sku-59"), "excluded or disabled products were recommended");
  console.log(recs.strategy, ids);
  if (recs.items.length) {
    await widget.click(recs, recs.items[0].external_product_id);
    await widget.convert(recs, recs.items[0].external_product_id, { value: "12.00" });
  }
  const anon = await store.recommendations.forSession({ sessionId: "sess-smoke", recentProductIds: ["sku-3"], topN: 3 });
  console.log("session:", anon.items.map((i) => i.external_product_id));

  if (platformToken) {
    step("platform administration");
    const ops = publicClient.withCredentials({ platformToken });
    console.log(await ops.platform.status());
    console.log((await ops.platform.getTenant(tenant.id)).status, (await ops.platform.listAuditLogs()).items.length, "audit records");
  }

  step("cleanup");
  await admin.apiKeys.revoke(key.id);
  console.log("revoked", key.prefix);
  console.log("\nSMOKE TEST PASSED");
}

main(argument("--base-url", process.env.GRAPHREC_BASE_URL) ?? "http://localhost:8010", argument("--platform-token", process.env.PLATFORM_ADMIN_TOKEN)).catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
