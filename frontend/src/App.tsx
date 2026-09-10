import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { PlatformProvider } from './auth/PlatformContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'
import { OrdersListPage } from './pages/OrdersListPage'
import { OrderStatusPage } from './pages/OrderStatusPage'
import { OrderDetailPage } from './pages/OrderDetailPage'
import { PrintervalLoginPage } from './pages/PrintervalLoginPage'
import { UsersPage } from './pages/UsersPage'
import { DesignerBoardPage } from './pages/DesignerBoardPage'
import { OrderHistoryPage } from './pages/OrderHistoryPage'
import { FinancePage } from './pages/FinancePage'

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <PlatformProvider>
          <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/orders"
            element={
              <ProtectedRoute>
                <OrdersListPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/orders/:id"
            element={
              <ProtectedRoute>
                <OrderDetailPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/finance"
            element={
              <ProtectedRoute>
                <FinancePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/designer-board"
            element={
              <ProtectedRoute>
                <DesignerBoardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/order-history"
            element={
              <ProtectedRoute>
                <OrderHistoryPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/order-status"
            element={
              <ProtectedRoute>
                <OrderStatusPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/users"
            element={
              <ProtectedRoute>
                <UsersPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/printerval-login"
            element={
              <ProtectedRoute>
                <PrintervalLoginPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/my-tasks"
            element={<Navigate to="/orders" replace />}
          />
          <Route
            path="/allocation"
            element={<Navigate to="/orders" replace />}
          />
          <Route
            path="/kanban"
            element={<Navigate to="/orders" replace />}
          />
          <Route path="/" element={<Navigate to="/orders" replace />} />
        </Routes>
        </PlatformProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
