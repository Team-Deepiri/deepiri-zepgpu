import { ReactNode, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuthStore } from '@/stores/authStore'
import {
  LayoutDashboard, ListTodo, GitBranch, Cpu, LogOut, Menu, X,
  BarChart3, Calendar, Globe, Users, Shield, Zap, Bell,
  Activity
} from 'lucide-react'
import clsx from 'clsx'

interface LayoutProps {
  children: ReactNode
}

const navItems = [
  { href: '/', label: 'Dashboard', icon: LayoutDashboard, color: 'text-cyan-400' },
  { href: '/tasks', label: 'Tasks', icon: ListTodo, color: 'text-green-400' },
  { href: '/pipelines', label: 'Pipelines', icon: GitBranch, color: 'text-purple-400' },
  { href: '/gpus', label: 'GPUs', icon: Cpu, color: 'text-orange-400' },
  { href: '/schedules', label: 'Schedules', icon: Calendar, color: 'text-cyan-400' },
  { href: '/metrics', label: 'Metrics', icon: BarChart3, color: 'text-indigo-400' },
  { href: '/control', label: 'Control', icon: Zap, color: 'text-red-400' },
  { href: '/alerts', label: 'Alerts', icon: Bell, color: 'text-yellow-400' },
  { href: '/namespaces', label: 'Namespaces', icon: Shield, color: 'text-teal-400' },
  { href: '/cloud', label: 'Cloud', icon: Globe, color: 'text-sky-400' },
  { href: '/users', label: 'Users', icon: Users, color: 'text-violet-400' },
]

export default function Layout({ children }: LayoutProps) {
  const location = useLocation()
  const logout = useAuthStore((state) => state.logout)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)

  return (
    <div className="min-h-screen bg-slate-900">
      {/* Top Nav */}
      <nav className="bg-slate-800/95 border-b border-slate-700/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="max-w-[1920px] mx-auto px-4 sm:px-6">
          <div className="flex items-center justify-between h-14">
            {/* Logo */}
            <Link to="/" className="flex items-center gap-3 flex-shrink-0">
              <div className="w-8 h-8 bg-gradient-to-br from-cyan-400 via-blue-500 to-purple-600 rounded-lg flex items-center justify-center shadow-lg shadow-blue-500/30">
                <Activity className="w-5 h-5 text-white" />
              </div>
              <span className="text-lg font-bold text-white hidden sm:block">ZepGPU</span>
              <span className="hidden md:block text-xs bg-gradient-to-r from-cyan-500 to-purple-500 text-white px-2 py-0.5 rounded-full font-medium">Control Hub</span>
            </Link>

            {/* Desktop Nav */}
            <div className="hidden xl:flex items-center gap-0.5">
              {navItems.map((item) => {
                const Icon = item.icon
                const isActive = location.pathname === item.href
                return (
                  <Link
                    key={item.href}
                    to={item.href}
                    className={clsx(
                      'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all',
                      isActive
                        ? `bg-slate-700 ${item.color}`
                        : 'text-slate-400 hover:bg-slate-700/50 hover:text-white'
                    )}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {item.label}
                  </Link>
                )
              })}
            </div>

            {/* Right side */}
            <div className="flex items-center gap-2">
              {/* Status dot */}
              <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 bg-green-500/10 border border-green-500/20 rounded-full">
                <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                <span className="text-xs text-green-400 font-medium">System Online</span>
              </div>

              {/* User */}
              <div className="flex items-center gap-2 pl-2 border-l border-slate-700">
                <button
                  onClick={logout}
                  className="flex items-center gap-2 px-3 py-1.5 text-xs text-slate-300 hover:text-white hover:bg-slate-700 rounded-lg transition-colors"
                >
                  <LogOut className="w-3.5 h-3.5" />
                  <span className="hidden sm:inline">Logout</span>
                </button>
                <button
                  className="xl:hidden p-2 text-slate-300 hover:text-white"
                  onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                >
                  {mobileMenuOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Mobile Nav */}
        {mobileMenuOpen && (
          <div className="xl:hidden border-t border-slate-700">
            <div className="px-2 py-3 grid grid-cols-2 sm:grid-cols-3 gap-1">
              {navItems.map((item) => {
                const Icon = item.icon
                const isActive = location.pathname === item.href
                return (
                  <Link
                    key={item.href}
                    to={item.href}
                    onClick={() => setMobileMenuOpen(false)}
                    className={clsx(
                      'flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                      isActive
                        ? `bg-slate-700 ${item.color}`
                        : 'text-slate-300 hover:bg-slate-700/50'
                    )}
                  >
                    <Icon className="w-4 h-4" />
                    {item.label}
                  </Link>
                )
              })}
            </div>
          </div>
        )}
      </nav>

      {/* Main Content */}
      <main className="max-w-[1920px] mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {children}
      </main>
    </div>
  )
}
