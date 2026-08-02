import { useEffect, useState } from "react";
import { disableProduct, listProducts } from "../api/products";
import type { ProductResource } from "../api/types";
import { getAuthSession } from "../auth/session";
import { Brand } from "../components/Brand";
import { Navbar } from "../components/Navbar";
import { SpaLink } from "../components/SpaLink";

export function ProductsPage() {
  const session = getAuthSession();
  const [products, setProducts] = useState<ProductResource[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (session) {
      void loadProducts();
    }
  }, [session]);

  async function loadProducts() {
    if (!session) return;
    setIsLoading(true);
    try {
      const data = await listProducts(session.access_token);
      setProducts(data.items);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load products");
    } finally {
      setIsLoading(false);
    }
  }

  async function handleDisable(externalId: string) {
    if (!session) return;
    try {
      await disableProduct(session.access_token, externalId);
      await loadProducts();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to disable product");
    }
  }

  if (!session) {
    return (
      <main className="centered-page protected-gap">
        <Brand />
        <p className="eyebrow">Authentication required</p>
        <h1>Sign in to manage product catalog.</h1>
        <a className="button primary" href="/auth/login?returnTo=%2Fapp%2Fproducts">
          Sign in
        </a>
      </main>
    );
  }

  return (
    <main className="workspace-shell">
      <Navbar />
      <section className="subscription-heading">
        <div>
          <p className="eyebrow">Catalog / Products</p>
          <h1>Tenant Product Catalog</h1>
          <p className="lede compact">Browse and manage tenant products for recommendation eligibility.</p>
        </div>
        <div className="page-actions">
          <SpaLink className="button primary" href="/app/data">
            Database Sync & Upload
          </SpaLink>
          <button className="button secondary" type="button" onClick={() => void loadProducts()} disabled={isLoading}>
            {isLoading ? "Refreshing…" : "Refresh"}
          </button>
        </div>
      </section>

      {error ? (
        <div className="error-panel" role="alert" style={{ marginBottom: "1.5rem" }}>
          <strong>Catalog Error</strong>
          <p>{error}</p>
        </div>
      ) : null}

      <section className="limits-card">
        <div className="limits-card-heading">
          <p className="eyebrow">Active Products</p>
          <h2>Catalog Items ({products.length})</h2>
        </div>
        {products.length === 0 ? (
          <div className="empty-keys" role="status" style={{ marginTop: "1rem" }}>
            <h2>No products found</h2>
            <p>Use Database Upload to synchronize your product database.</p>
          </div>
        ) : (
          <div className="key-list">
            {products.map((prod) => (
              <article className="key-card" key={prod.id}>
                <div className="key-card-title">
                  <div>
                    <h2>{prod.title}</h2>
                    <code>{prod.external_id}</code>
                  </div>
                  <span className={`key-status ${prod.is_active ? "key-active" : "key-revoked"}`}>
                    {prod.is_active ? "Active" : "Disabled"}
                  </span>
                </div>
                <dl className="key-metadata">
                  <div>
                    <dt>Price</dt>
                    <dd>${prod.price}</dd>
                  </div>
                  <div>
                    <dt>Category</dt>
                    <dd>{prod.category || "Unassigned"}</dd>
                  </div>
                  <div>
                    <dt>Status</dt>
                    <dd>{prod.availability_status}</dd>
                  </div>
                </dl>
                {prod.is_active ? (
                  <div className="key-actions">
                    <button className="button danger compact-btn" onClick={() => void handleDisable(prod.external_id)}>
                      Disable Product
                    </button>
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
