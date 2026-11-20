/**
 * Contract check (Phase 3): the hand-written console types in ./types must agree
 * with the types generated from the server's OpenAPI document (./schema.gen.ts,
 * produced by `npm run gen:api`). `tsc` fails on any drift:
 *
 * - responses: what the server returns must satisfy what the console reads;
 * - requests:  what the console sends must satisfy what the server accepts.
 *
 * CI regenerates schema.gen.ts from openapi.json and fails if it changed.
 */
import type { components } from "./schema.gen";
import type * as T from "./types";

type S = components["schemas"];
/**
 * The OpenAPI document types enums as plain strings and marks defaulted fields
 * optional, so values are compared after widening literals to their base type and
 * making every field optional; field *names* are compared exactly.
 */
type Widen<V> = V extends string ? string : V extends number ? number : V extends boolean ? boolean
  : V extends null | undefined ? V : V extends readonly (infer I)[] ? Widen<I>[] : V extends object ? Loose<V> : V;
type Loose<O> = { [K in keyof O]?: Widen<Exclude<O[K], undefined>> | null };
/** Fields the reader expects that the writer never sends. */
type Missing<Reader, Writer> = Exclude<keyof Reader, keyof Writer>;
/** true when every field of Reader exists on Writer with a compatible type; otherwise the missing names. */
type Fits<Writer extends Loose<Reader>, Reader> = [Missing<Reader, Writer>] extends [never] ? true : Missing<Reader, Writer>;
/** Compiles only for true: a failure prints the missing field names. */
type Expect<T extends true> = T;

export type ResponseContract = [
  Expect<Fits<S["TenantRegistrationResponse"], T.TenantRegistrationResult>>,
  Expect<Fits<S["TenantUserResource"], T.TenantUserResource>>,
  Expect<Fits<S["TenantUserInviteResponse"], T.TenantUserInvitation>>,
  Expect<Fits<S["AuthTokenPair"], T.AuthTokenPair>>,
  Expect<Fits<S["ApiKeyResponse"], T.ApiKeyResource>>,
  Expect<Fits<S["ApiKeySecretResponse"], T.ApiKeySecretResource>>,
  Expect<Fits<S["SubscriptionResponse"], T.SubscriptionResult>>,
  Expect<Fits<S["PlanChangeRequestResource"], T.PlanChangeRequest>>,
  Expect<Fits<S["PlanChangeRequestList"], T.PlanChangeRequestList>>,
  Expect<Fits<S["PlatformPlanChangeRequest"], T.PlatformPlanRequest>>,
  Expect<Fits<S["PlatformPlanChangeRequestList"], T.PlatformPlanRequestList>>,
  Expect<Fits<S["PlanRequestDecisionResult"], T.PlanRequestDecisionResult>>,
  Expect<Fits<S["UsageDimension"], T.UsageDimension>>,
  Expect<Fits<S["UsageSummaryResponse"], T.UsageSummaryResult>>,
  Expect<Fits<S["ProductBulkUpsertResponse"], T.ProductBulkUpsertResponse>>,
  Expect<Fits<S["CatalogSyncResource"], T.CatalogSyncResource>>,
  Expect<Fits<S["ProductResource"], T.ProductResource>>,
  Expect<Fits<S["ProductListResponse"], T.ProductListResponse>>,
  Expect<Fits<S["EventSubmitResponse"], T.EventSubmitResponse>>,
  Expect<Fits<S["EventRecord"], T.EventRecord>>,
  Expect<Fits<S["EventBatchResponse"], T.EventBatchResponse>>,
  Expect<Fits<S["DatasetSnapshotResource"], T.DatasetSnapshotResource>>,
  Expect<Fits<S["DatasetUploadResponse"], T.DatasetUploadResponse>>,
  Expect<Fits<S["ModelVersionResource"], T.ModelVersionResource>>,
  Expect<Fits<S["TrainingJobResource"], T.TrainingJobResource>>,
  Expect<Fits<S["DeploymentStatus"], T.DeploymentStatus>>,
  Expect<Fits<S["QualitySummary"], T.QualitySummary>>,
  Expect<Fits<S["MetricsSummary"], T.MetricsSummary>>,
  Expect<Fits<S["PlatformTenantResource"], T.PlatformTenant>>,
  Expect<Fits<S["PlatformPlanResource"], T.PlatformPlan>>,
  Expect<Fits<S["PlatformQuotaOverride"], T.PlatformQuotaOverride>>,
  Expect<Fits<S["PlatformFailureItem"], T.PlatformFailure>>,
  Expect<Fits<S["PlatformAuditItem"], T.PlatformAudit>>,
  Expect<Fits<S["PlatformStatus"], T.PlatformStatus>>,
  Expect<Fits<S["RetrainingPolicyResource"], T.RetrainingPolicy>>,
  Expect<Fits<S["RecommendationPolicyResource"], T.RecommendationPolicy>>,
  Expect<Fits<S["CapacityEventResource"], T.CapacityEvent>>,
  Expect<Fits<S["ScalingStatus"], T.ScalingStatus>>,
  Expect<Fits<S["RecommendationResponse"], T.RecommendationResult>>,
  Expect<Fits<S["TenantStatusResponse"], T.TenantStatus>>,
  Expect<Fits<S["OperatorSession"], T.OperatorSession>>,
  Expect<Fits<S["OperatorResource"], T.PlatformOperator>>,
  Expect<Fits<S["Me"], T.PlatformMe>>,
  Expect<Fits<S["MetaResponse"], T.ProductMeta>>,
  Expect<Fits<S["PublicPlan"], T.PublicPlan>>,
  Expect<Fits<S["TenantAuditItem"], T.TenantAuditItem>>,
  Expect<Fits<S["PlatformTenantUsage"], T.PlatformTenantUsage>>,
];

export type RequestContract = [
  Expect<Fits<T.TenantRegistrationInput, S["TenantRegistrationRequest"]>>,
  Expect<Fits<T.LoginInput, S["LoginRequest"]>>,
  Expect<Fits<T.SetupPasswordInput, S["SetupPasswordRequest"]>>,
  Expect<Fits<T.RecoverPasswordInput, S["RecoverPasswordRequest"]>>,
  Expect<Fits<T.ApiKeyCreateInput, S["ApiKeyCreateRequest"]>>,
  Expect<Fits<T.ApiKeyRotateInput, S["ApiKeyRotateRequest"]>>,
  Expect<Fits<T.ProductUpsert, S["ProductUpsert"]>>,
  Expect<Fits<T.EventSubmit, S["EventSubmit"]>>,
  Expect<Fits<T.TrainingJobCreate, S["TrainingJobCreate"]>>,
  Expect<Fits<T.RetrainingPolicyInput, S["RetrainingPolicyUpdate"]>>,
  Expect<Fits<T.RecommendationPolicyInput, S["RecommendationPolicyUpdate"]>>,
];
