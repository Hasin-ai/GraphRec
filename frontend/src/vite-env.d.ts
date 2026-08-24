/// <reference types="vite/client" />

/**
 * The environment this build was given.
 *
 * Without this declaration `import.meta.env.VITE_*` is `any`, and `any` is how
 * a typo in a variable name becomes a `BASE_URL` of `undefined` that falls
 * through to a default and points the integration page at the wrong host. One
 * variable, declared, so the compiler knows the difference between "not set"
 * and "not a thing".
 */
interface ImportMetaEnv {
  /** Where the data plane lives. Shown on `/integration` and copied by hand
   *  into the customer's own service, so a wrong value here is a wrong value
   *  in somebody else's deployment. */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
