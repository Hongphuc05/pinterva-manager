import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { ProtectedRoute } from './auth/ProtectedRoute'
import { LoginPage } from './pages/LoginPage'

function App() {
  return (
    <BrowserRouter basename="/spa">
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/orders"
            element={
              <ProtectedRoute>
                <div className="p-6">Danh sách đơn (Task 4)</div>
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
