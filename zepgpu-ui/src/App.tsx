import { useEffect } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import Layout from '@/components/Layout'
import RouteErrorBoundary from '@/components/RouteErrorBoundary'
import Dashboard from '@/pages/Dashboard'
import Tasks from '@/pages/Tasks'
import TaskDetail from '@/pages/TaskDetail'
import NewTask from '@/pages/NewTask'
import Pipelines from '@/pages/Pipelines'
import GPUs from '@/pages/GPUs'
import Login from '@/pages/Login'
import Register from '@/pages/Register'
import Schedules from '@/pages/Schedules'
import Metrics from '@/pages/Metrics'
import Namespaces from '@/pages/Namespaces'
import Cloud from '@/pages/Cloud'
import Users from '@/pages/Users'
import Control from '@/pages/Control'
import Alerts from '@/pages/Alerts'
import Vpn from '@/pages/Vpn'
import Ledger from '@/pages/Ledger'
import Rooms from '@/pages/Rooms'
import RoomDetail from '@/pages/RoomDetail'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((state) => state.token)

  useEffect(() => {
    const stored = localStorage.getItem('token')
    if (stored && !useAuthStore.getState().token) {
      useAuthStore.setState({ token: stored, isAuthenticated: true })
    }
  }, [token])

  const effectiveToken = token ?? localStorage.getItem('token')

  if (!effectiveToken) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route
        path="/*"
        element={
          <ProtectedRoute>
            <Layout>
              <RouteErrorBoundary>
                <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/tasks" element={<Tasks />} />
                <Route path="/tasks/new" element={<NewTask />} />
                <Route path="/tasks/:id" element={<TaskDetail />} />
                <Route path="/pipelines" element={<Pipelines />} />
                <Route path="/gpus" element={<GPUs />} />
                <Route path="/schedules" element={<Schedules />} />
                <Route path="/metrics" element={<Metrics />} />
                <Route path="/control" element={<Control />} />
                <Route path="/alerts" element={<Alerts />} />
                <Route path="/namespaces" element={<Namespaces />} />
                <Route path="/cloud" element={<Cloud />} />
                <Route path="/rooms" element={<Rooms />} />
                <Route path="/rooms/:roomId" element={<RoomDetail />} />
                <Route path="/vpn" element={<Vpn />} />
                <Route path="/ledger" element={<Ledger />} />
                <Route path="/users" element={<Users />} />
                </Routes>
              </RouteErrorBoundary>
            </Layout>
          </ProtectedRoute>
        }
      />
    </Routes>
  )
}

export default App
