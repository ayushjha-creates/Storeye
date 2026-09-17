import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { EdgeProvider } from './edge/EdgeContext'
import { ProtectedRoute, PublicOnlyRoute } from './auth/ProtectedRoute'
import { AppShell } from './components/layout/AppShell'
import { OfflineBanner } from './components/OfflineBanner'
import { ErrorBoundary } from './components/ErrorBoundary'
import { LandingPage } from './pages/Landing'
import { LoginPage } from './pages/Login'
import { DashboardPage } from './pages/Dashboard'
import { LiveStorePage } from './pages/LiveStore'
import { ReportsPage } from './pages/Reports'
import { CamerasPage } from './pages/Cameras'
import { CameraDetailPage } from './pages/CameraDetail'
import { ObservationsPage } from './pages/Observations'
import { ReconciliationPage } from './pages/Reconciliation'
import { InventoryPage } from './pages/Inventory'
import { ReceiveSmartPage } from './pages/ReceiveSmart'
import { BillingPage } from './pages/Billing'
import { ProductsPage } from './pages/Products'
import { CustomersPage } from './pages/Customers'
import { SettingsPage } from './pages/Settings'
import { ProductIntelligencePage } from './pages/ProductIntelligence'
import { ShelfIntelligencePage } from './pages/ShelfIntelligence'
import { AlertsPage } from './pages/Alerts'
import { JourneysPage } from './pages/Journeys'
import { JourneyDetailPage } from './pages/JourneyDetail'
import { InsightsPage } from './pages/Insights'
import { DemoControlCenterPage } from './pages/DemoControlCenter'
import { DemoPresentationPage } from './pages/DemoPresentation'
import { NotFoundPage } from './pages/NotFound'

function App() {
  return (
    <AuthProvider>
      <EdgeProvider>
        <BrowserRouter>
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route
                path="/login"
                element={
                  <PublicOnlyRoute>
                    <LoginPage />
                  </PublicOnlyRoute>
                }
              />
              <Route
                path="/app"
                element={
                  <ProtectedRoute>
                    <AppShell />
                  </ProtectedRoute>
                }
              >
                <Route index element={<DashboardPage />} />
                <Route path="live-store" element={<LiveStorePage />} />
                <Route path="cameras" element={<CamerasPage />} />
                <Route path="cameras/:cameraId" element={<CameraDetailPage />} />
                <Route path="observations" element={<ObservationsPage />} />
                <Route path="reconciliation" element={<ReconciliationPage />} />
                <Route path="inventory" element={<InventoryPage />} />
                <Route path="inventory/receive" element={<ReceiveSmartPage />} />
                <Route path="billing" element={<BillingPage />} />
                <Route path="products" element={<ProductsPage />} />
                <Route path="customers" element={<CustomersPage />} />
                <Route path="product-intelligence" element={<ProductIntelligencePage />} />
                <Route path="shelf-intelligence" element={<ShelfIntelligencePage />} />
                <Route path="alerts" element={<AlertsPage />} />
                <Route path="journeys" element={<JourneysPage />} />
                <Route path="journeys/:journeyId" element={<JourneyDetailPage />} />
                <Route path="insights" element={<InsightsPage />} />
                <Route path="demo" element={<DemoControlCenterPage />} />
                <Route path="demo/presentation" element={<DemoPresentationPage />} />
                <Route path="reports" element={<ReportsPage />} />
                <Route path="settings" element={<SettingsPage />} />
              </Route>
              <Route path="*" element={<NotFoundPage />} />
            </Routes>
          </ErrorBoundary>
          <OfflineBanner />
        </BrowserRouter>
      </EdgeProvider>
    </AuthProvider>
  )
}

export default App