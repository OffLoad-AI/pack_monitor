import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Compare } from "./pages/Compare";
import { ComparisonDetail } from "./pages/ComparisonDetail";
import { History } from "./pages/History";
import { Settings } from "./pages/Settings";

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Compare />} />
          <Route path="/comparisons/:id" element={<ComparisonDetail />} />
          <Route path="/history" element={<History />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
