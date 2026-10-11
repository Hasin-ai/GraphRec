// Shape of SDK_REFERENCE, produced by scripts/build_sdk_docs.py.

export interface SdkParam {
  name: string;
  type: string;
  default: string | null;
  required: boolean;
  kind: "positional" | "keyword" | "varargs" | "kwargs";
  description?: string;
}

export interface SdkRoute {
  key: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  path: string;
  auth: "none" | "optional" | "any" | "bearer";
  scopes: string[];
  idempotent: boolean;
}

export interface SdkMethod {
  name: string;
  call: string;
  signature: string;
  doc: string;
  params: SdkParam[];
  returns: string;
  routes: SdkRoute[];
}

export interface SdkResource {
  id: string;
  path: string;
  title: string;
  className: string;
  asyncClass: string | null;
  doc: string;
  methods: SdkMethod[];
  ctor?: string;
  contextManager?: boolean;
}

export interface SdkNamespace {
  name: string;
  path: string;
  doc: string;
  resources: SdkResource[];
}

export interface SdkError {
  name: string;
  base: string;
  doc: string;
  statuses: number[];
  codes: string[];
}

export interface SdkReference {
  version: string;
  package: string;
  requiresPython: string;
  dependencies: string[];
  constants: Record<string, string | number>;
  clientDoc: string;
  clientParams: SdkParam[];
  clientMethods: SdkMethod[];
  namespaces: SdkNamespace[];
  helpers: SdkResource[];
  errors: SdkError[];
  enums: Array<{ name: string; values: string[] }>;
  scopeSets: Record<string, string[] | Record<string, string[]>>;
  examples: Array<{ file: string; title: string; code: string }>;
  stats: { methods: number; routes: number; routesCovered: number; uncoveredRoutes: string[] };
}
