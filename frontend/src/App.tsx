import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "@/components/AppShell";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { PublicShell } from "@/components/PublicShell";
import { AnalyticsPage } from "@/pages/Analytics";
import { LeadQueuePage } from "@/pages/LeadQueue";
import { LoginPage } from "@/pages/Login";
import { OutreachPage } from "@/pages/Outreach";
import { PropertyDetailPage } from "@/pages/PropertyDetail";
import { PublicPropertyDetailPage } from "@/pages/PublicPropertyDetail";
import { SearchLandingPage } from "@/pages/SearchLanding";
import { SearchResultsPage } from "@/pages/SearchResults";

export default function App() {
  return (
    <Routes>
      {/* Admin login (public) */}
      <Route path="/login" element={<LoginPage />} />

      {/* Public user flow (no auth) */}
      <Route element={<PublicShell />}>
        <Route index element={<Navigate to="/search" replace />} />
        <Route path="/search" element={<SearchLandingPage />} />
        <Route path="/search/results" element={<SearchResultsPage />} />
        <Route path="/search/property/:id" element={<PublicPropertyDetailPage />} />
      </Route>

      {/* Admin dashboard (authenticated) */}
      <Route
        element={
          <ProtectedRoute>
            <AppShell />
          </ProtectedRoute>
        }
      >
        <Route path="/admin" element={<Navigate to="/admin/leads" replace />} />
        <Route path="/admin/leads" element={<LeadQueuePage />} />
        <Route path="/admin/properties/:id" element={<PropertyDetailPage />} />
        <Route path="/admin/outreach" element={<OutreachPage />} />
        <Route path="/admin/analytics" element={<AnalyticsPage />} />

        {/* Legacy admin routes — keep working for any saved bookmarks. */}
        <Route path="/leads" element={<Navigate to="/admin/leads" replace />} />
        <Route
          path="/properties/:id"
          element={<LegacyPropertyRedirect />}
        />
        <Route path="/outreach" element={<Navigate to="/admin/outreach" replace />} />
        <Route path="/analytics" element={<Navigate to="/admin/analytics" replace />} />
      </Route>

      {/* Anything else → public search landing. */}
      <Route path="*" element={<Navigate to="/search" replace />} />
    </Routes>
  );
}

function LegacyPropertyRedirect() {
  const path = window.location.pathname.replace("/properties/", "/admin/properties/");
  return <Navigate to={path} replace />;
}
