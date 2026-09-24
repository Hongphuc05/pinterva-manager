import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { PlatformProvider } from './auth/PlatformContext'
import { GallerySyncProvider } from './context/GallerySyncContext'
import { ToastProvider } from './context/ToastContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'
import { OrdersListPage } from './pages/OrdersListPage'
import { OrderDetailPage } from './pages/OrderDetailPage'
import { UsersPage } from './pages/UsersPage'
import { DesignerBoardPage } from './pages/DesignerBoardPage'
import { DesignerSubmissionsPage } from './pages/DesignerSubmissionsPage'
import { OrderHistoryPage } from './pages/OrderHistoryPage'
import { FinancePage } from './pages/FinancePage'
import { DuplicateBoardPage } from './pages/DuplicateBoardPage'
import { PlatformHubPage } from './pages/PlatformHubPage'
import { TelegramManagementPage } from './pages/TelegramManagementPage'
import { DuplicateReviewPage } from './pages/DuplicateReviewPage'
import { SupportQueuePage } from './pages/SupportQueuePage'

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <PlatformProvider>
          <ToastProvider>
            <GallerySyncProvider>
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
              <ProtectedRoute allowedRoles={['admin']}>
                <DesignerBoardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/designer-submissions"
            element={
              <ProtectedRoute allowedRoles={['admin', 'support']}>
                <DesignerSubmissionsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/order-history"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <OrderHistoryPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/order-status"
            element={<Navigate to="/orders?view=sync" replace />}
          />
          <Route
            path="/users"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <UsersPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/platform-hub"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <PlatformHubPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/telegram-management"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <TelegramManagementPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/duplicate-review"
            element={
              <ProtectedRoute allowedRoles={['support']}>
                <DuplicateReviewPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/support-queue"
            element={
              <ProtectedRoute allowedRoles={['support']}>
                <SupportQueuePage />
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
            element={
              <ProtectedRoute allowedRoles={['admin', 'designer-trello']}>
                <DuplicateBoardPage />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<Navigate to="/orders" replace />} />
        </Routes>
            </GallerySyncProvider>
          </ToastProvider>
        </PlatformProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
