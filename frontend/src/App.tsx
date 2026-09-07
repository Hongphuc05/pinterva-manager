import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { PlatformProvider } from './auth/PlatformContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'
import { OrdersListPage } from './pages/OrdersListPage'
import { OrderDetailPage } from './pages/OrderDetailPage'
import { PrintervalLoginPage } from './pages/PrintervalLoginPage'
import { AllocationBoardPage } from './pages/AllocationBoardPage'
import { MyTasksPage } from './pages/MyTasksPage'
import { KanbanPage } from './pages/KanbanPage'
import { UsersPage } from './pages/UsersPage'

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
            path="/allocation"
            element={
              <ProtectedRoute>
                <AllocationBoardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/my-tasks"
            element={
              <ProtectedRoute>
                <MyTasksPage />
              </ProtectedRoute>
            }
          />
          <Route path="/kanban" element={<ProtectedRoute><KanbanPage /></ProtectedRoute>} />
          <Route path="/" element={<Navigate to="/orders" replace />} />
        </Routes>
        </PlatformProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
