import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { ToastProvider } from "./components/Toast";
import { Dashboard } from "./pages/Dashboard";
import { FindingDetail } from "./pages/FindingDetail";
import { ProductDetail, Products } from "./pages/Products";
import { ReviewQueue } from "./pages/ReviewQueue";
import { RunProgress } from "./pages/RunProgress";
import { Runs } from "./pages/Runs";
import { Settings } from "./pages/Settings";

export function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Dashboard />} />
            <Route path="/queue" element={<ReviewQueue />} />
            <Route path="/findings/:id" element={<FindingDetail />} />
            <Route path="/products" element={<Products />} />
            <Route path="/products/:id" element={<ProductDetail />} />
            <Route path="/runs" element={<Runs />} />
            <Route path="/runs/:id" element={<RunProgress />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </ToastProvider>
  );
}
