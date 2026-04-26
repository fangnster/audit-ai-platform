import { useEffect, useRef } from 'react'
import toast from 'react-hot-toast'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

export function useCaseWebSocket(caseId: string) {
  const ws = useRef<WebSocket | null>(null)
  const qc = useQueryClient()
  const { t } = useTranslation()

  useEffect(() => {
    if (!caseId) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/cases/${caseId}`

    const connect = () => {
      ws.current = new WebSocket(wsUrl)

      ws.current.onopen = () => {
        console.log('WS Connected to case:', caseId)
      }

      ws.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          
          if (data.type === 'section_updated') {
            toast.success(t('fullDraftRewritten'))
            qc.invalidateQueries({ queryKey: ['drafts', caseId] })
            qc.invalidateQueries({ queryKey: ['agentTasks', caseId] })
          } else if (data.type === 'fact_fixed') {
            toast.success('事实更新，相关文案已同步刷新')
            qc.invalidateQueries({ queryKey: ['drafts', caseId] })
          } else if (data.type === 'rfi_generated') {
            toast.success('RFI 补件回复已生成')
            qc.invalidateQueries({ queryKey: ['agentTasks', caseId] })
          }
        } catch (err) {
          console.error('WS parse error', err)
        }
      }

      ws.current.onclose = () => {
        console.log('WS Disconnected')
        // reconnect logic
        setTimeout(connect, 3000)
      }
    }

    connect()

    return () => {
      if (ws.current) {
        ws.current.onclose = null
        ws.current.close()
      }
    }
  }, [caseId, qc, t])

  const sendMessage = (msg: any) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      ws.current.send(JSON.stringify(msg))
    }
  }

  return { sendMessage }
}
