/**
 * Snapshot data, train a DGSR model, review it and put it into service.
 *
 *   export GRAPHREC_ADMIN_EMAIL=owner@acme.example GRAPHREC_ADMIN_PASSWORD=...
 *   npm run build && node examples/train-and-deploy.ts
 */
import { GraphRec, StateConflictError } from "@graphrec/sdk";

const MIN_NDCG = 0.5;

function env(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`${name} is not set`);
  return value;
}

async function main(): Promise<void> {
  const admin = new GraphRec({ email: env("GRAPHREC_ADMIN_EMAIL"), password: env("GRAPHREC_ADMIN_PASSWORD") });

  const snapshot = await admin.datasets.createSnapshot();
  console.log(`snapshot ${snapshot.id}: ${snapshot.event_count} events, ${snapshot.product_count} products, ${snapshot.user_count} users`);

  let job = await admin.trainingJobs.create({
    dataset_snapshot_id: snapshot.id,
    configuration: { batch_size: 256, learning_rate: 0.001, gnn_layers: 2 },
  });
  job = await admin.trainingJobs.wait(job.id, { timeoutMs: 1_800_000, pollIntervalMs: 10_000 });
  if (job.status !== "succeeded" || job.model_version_id === null) {
    throw new Error(`training ${job.status}: ${job.failure_reason ?? "no reason given"}`);
  }

  const candidate = await admin.modelVersions.get(job.model_version_id);
  const previous = await admin.modelVersions.getActive();
  console.log(`candidate ${candidate.version_tag}:`, Object.keys(candidate.metrics).length ? candidate.metrics : "no offline metrics");
  const ndcg = candidate.metrics.ndcg_at_10;
  if (typeof ndcg === "number" && ndcg < MIN_NDCG) {
    throw new Error(`ndcg@10 ${ndcg.toFixed(3)} below threshold - not activating`);
  }
  if (ndcg === undefined) {
    // The current training slice indexes placeholder embeddings and reports no metrics.
    console.log("warning: no ndcg_at_10 reported; activating without a quality gate");
  }

  await admin.modelVersions.activate(candidate.id);
  const status = await admin.deployment.get();
  console.log(`deployment ${status.status}, ready replicas ${status.ready_replicas}`);

  const metrics = await admin.metrics.summary();
  if (previous !== null && metrics.error_rate > 0.05) {
    console.log("error rate too high, rolling back");
    await admin.modelVersions.rollback(previous.id);
  }

  for (const version of (await admin.modelVersions.list()).items) {
    if (version.status !== "retired") continue;
    try {
      await admin.modelVersions.archive(version.id);
    } catch (error) {
      if (!(error instanceof StateConflictError)) throw error;
    }
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
