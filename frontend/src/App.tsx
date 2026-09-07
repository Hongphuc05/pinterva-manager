import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'
import { OrdersListPage } from './pages/OrdersListPage'
import { OrderDetailPage } from './pages/OrderDetailPage'
import { PrintervalLoginPage } from './pages/PrintervalLoginPage'

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
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
            path="/printerval-login"
            element={
              <ProtectedRoute>
                <PrintervalLoginPage />
              </ProtectedRoute>
            }
          />
          <Route path="/" element={<Navigate to="/orders" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}

export default App
