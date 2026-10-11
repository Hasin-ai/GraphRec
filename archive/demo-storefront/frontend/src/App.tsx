import { Route, Routes } from "react-router-dom";
import { CartDrawer } from "./components/CartDrawer";
import { DemoRail } from "./components/DemoRail";
import { Header } from "./components/Header";
import { Toast } from "./components/Toast";
import { useStore } from "./lib/store";
import { CatalogPage } from "./pages/CatalogPage";
import { ComparePage } from "./pages/ComparePage";
import { OrderPage } from "./pages/OrderPage";
import { ProductPage } from "./pages/ProductPage";

function NotFound() {
  return (
    <main className="fct-main" style={{ paddingTop: "var(--space-8)" }}>
      <h1>Nothing here.</h1>
      <p className="fct-muted">That page is not part of the demo store.</p>
    </main>
  );
}

export function App() {
  const { live, sessionError, lastProvenance } = useStore();
  return (
    <div className="fct-page">
      <Header />
      <p aria-live="polite" className="sr-only">
        {live}
      </p>
      {sessionError && (
        <div className="fct-main">
          <div className="fct-error" role="alert" style={{ marginTop: "var(--space-4)" }}>
            <p className="title">The storefront server is not reachable</p>
            <p className="body">{sessionError} Start it with `uvicorn app.main:app --port 5190` and reload.</p>
          </div>
        </div>
      )}
      <Routes>
        <Route path="/" element={<CatalogPage />} />
        <Route path="/products/:id" element={<ProductPage />} />
        <Route path="/demo/compare" element={<ComparePage />} />
        <Route path="/order/:id" element={<OrderPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
      <footer className="fct-footer">
        <span>Facet — a GraphRec demonstration store. Products, prices and orders are fictional.</span>
        <span className="mono">{lastProvenance ? `${lastProvenance.rawStrategy} · ${lastProvenance.modelVersionId ?? "no model"} · ${lastProvenance.proofStatus}` : "no recommendation requested yet"}</span>
      </footer>
      <CartDrawer />
      <DemoRail />
      <Toast />
    </div>
  );
}
