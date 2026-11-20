import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { Header } from "./components/Header";
import { Insight } from "./components/Insight";
import { DemoProvider, useDemo } from "./demo";
import { Browse } from "./pages/Browse";
import { FilmPage } from "./pages/FilmPage";
import { Home } from "./pages/Home";

function Shell() {
  const { insightOpen, toast } = useDemo();
  return (
    <div className={`app ${insightOpen ? "with-insight" : ""}`}>
      <Header />
      <div className="layout">
        <main>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/browse" element={<Browse />} />
            <Route path="/browse/:genre" element={<Browse />} />
            <Route path="/film/:id" element={<FilmPage />} />
            <Route path="*" element={<div className="page empty"><h1>Page not found</h1><p className="muted">That address isn't part of Reel.</p><p><Link className="btn primary" to="/">Back to Home</Link></p></div>} />
          </Routes>
        </main>
        <Insight />
      </div>
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <DemoProvider><Shell /></DemoProvider>
    </BrowserRouter>
  );
}
