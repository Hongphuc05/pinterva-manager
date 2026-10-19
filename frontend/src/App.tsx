import { Suspense, lazy, type ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { PlatformProvider } from './auth/PlatformContext'
import { GallerySyncProvider } from './context/GallerySyncContext'
import { ToastProvider } from './context/ToastContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'
import { RootRedirect } from './auth/RootRedirect'
import { PrintervalAlertToasts } from './features/alerts/PrintervalAlertToasts'
import { PrintervalChatToasts } from './features/alerts/PrintervalChatToasts'
import { WorkerProvider } from './features/worker/WorkerProvider'
import { ConsentDialog } from './features/worker/ConsentDialog'

const OrdersListPage = lazy(() => import('./pages/OrdersListPage').then((m) => ({ default: m.OrdersListPage })))
const OrderDetailPage = lazy(() => import('./pages/OrderDetailPage').then((m) => ({ default: m.OrderDetailPage })))
const UsersPage = lazy(() => import('./pages/UsersPage').then((m) => ({ default: m.UsersPage })))
const DesignerBoardPage = lazy(() => import('./pages/DesignerBoardPage').then((m) => ({ default: m.DesignerBoardPage })))
const DesignerSubmissionsPage = lazy(() => import('./pages/DesignerSubmissionsPage').then((m) => ({ default: m.DesignerSubmissionsPage })))
const OrderHistoryPage = lazy(() => import('./pages/OrderHistoryPage').then((m) => ({ default: m.OrderHistoryPage })))
const FinancePage = lazy(() => import('./pages/FinancePage').then((m) => ({ default: m.FinancePage })))
const DuplicateBoardPage = lazy(() => import('./pages/DuplicateBoardPage').then((m) => ({ default: m.DuplicateBoardPage })))
const PlatformHubPage = lazy(() => import('./pages/PlatformHubPage').then((m) => ({ default: m.PlatformHubPage })))
const TelegramManagementPage = lazy(() => import('./pages/TelegramManagementPage').then((m) => ({ default: m.TelegramManagementPage })))
const DuplicateReviewPage = lazy(() => import('./pages/DuplicateReviewPage').then((m) => ({ default: m.DuplicateReviewPage })))
const SupportQueuePage = lazy(() => import('./pages/SupportQueuePage').then((m) => ({ default: m.SupportQueuePage })))
const AccountantPaymentsPage = lazy(() => import('./pages/AccountantPaymentsPage').then((m) => ({ default: m.AccountantPaymentsPage })))

/** The toast provider, keyed by the signed-in user so the bell's history is theirs alone. */
function ScopedToastProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth()
  return <ToastProvider scope={user?.id ?? null}>{children}</ToastProvider>
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <PlatformProvider>
          <ScopedToastProvider>
            <GallerySyncProvider>
              <PrintervalAlertToasts />
              <PrintervalChatToasts />
              <WorkerProvider ConsentDialog={ConsentDialog}>
              <Suspense fallback={<div className="p-8 text-sm text-slate-500">Đang tải…</div>}>
              <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/orders"
            element={
              <ProtectedRoute allowedRoles={['admin', 'designer', 'designer-trello', 'support']}>
                <OrdersListPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/orders/:id"
            element={
              <ProtectedRoute allowedRoles={['admin', 'designer', 'designer-trello', 'support']}>
                <OrderDetailPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/finance"
            element={
              <ProtectedRoute allowedRoles={['admin', 'designer', 'designer-trello', 'support']}>
                <FinancePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/payments"
            element={
              <ProtectedRoute allowedRoles={['accountant']}>
                <AccountantPaymentsPage />
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
          <Route path="/" element={<RootRedirect />} />
        </Routes>
              </Suspense>
              </WorkerProvider>
            </GallerySyncProvider>
          </ScopedToastProvider>
        </PlatformProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
