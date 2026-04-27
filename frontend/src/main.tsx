import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import './i18n'
import App from './App'
import { AppToaster } from './components/AppToaster'
import { installToastHistoryRecorder } from './utils/notificationHistory'

const savedTheme = localStorage.getItem('ui-theme')
document.documentElement.dataset.theme = savedTheme === 'dark' ? 'dark' : 'light'
installToastHistoryRecorder()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, staleTime: 30_000 },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
        <AppToaster />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
)
