import { InputValidationError } from "../errors.js";
import { newIdempotencyKey } from "../ids.js";
import type { TenantRegistration, TenantRegistrationInput, TokenPair } from "../types.js";
import { Resource } from "./base.js";

export class Tenants extends Resource {
  /**
   * Create a tenant and its invited administrator (`POST /v1/tenants`).
   *
   * The `201` response carries a one-time `setup_token` for `auth.setupPassword`.
   * Pass the same `idempotencyKey` to retry safely: a replay returns the
   * original tenant with `replayed: true` and `setup_token: null`.
   */
  async register(input: TenantRegistrationInput, options: { idempotencyKey?: string } = {}): Promise<TenantRegistration> {
    if (!input.name?.trim()) throw new InputValidationError("name is required");
    if (!input.admin_email?.includes("@")) throw new InputValidationError("admin_email must be an email address");
    return this.client.request<TenantRegistration>("tenants.register", {
      json: { name: input.name.trim(), admin_email: input.admin_email.trim().toLowerCase() },
      idempotencyKey: options.idempotencyKey ?? newIdempotencyKey(),
    });
  }
}

export class Auth extends Resource {
  /** `POST /v1/auth/login`. The token lasts 15 minutes; there is no refresh endpoint. */
  async login(input: { email: string; password: string }): Promise<TokenPair> {
    if (!input.email || !input.password) throw new InputValidationError("email and password are required");
    return this.client.request<TokenPair>("auth.login", { json: { email: input.email.trim().toLowerCase(), password: input.password } });
  }

  /**
   * Activate an invited account with its one-time setup token
   * (`POST /v1/auth/setup-password`). Any rejected token raises
   * `AuthenticationError` with `code === "invalid_setup_token"`.
   */
  async setupPassword(input: { setupToken: string; password: string; email?: string }): Promise<TokenPair> {
    if (!input.setupToken || input.setupToken.length < 16) throw new InputValidationError("setupToken is required");
    if (!input.password || input.password.length < 8) throw new InputValidationError("password must be at least 8 characters");
    const body: Record<string, unknown> = { setup_token: input.setupToken, password: input.password };
    if (input.email) body.email = input.email.trim().toLowerCase();
    return this.client.request<TokenPair>("auth.setup_password", { json: body });
  }
}
