import { useEffect, useRef } from 'react'
import toast from 'react-hot-toast'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { notificationHistoryMeta } from '../utils/notificationHistory'

export function useCaseWebSocket(caseId: string) {
  const ws = useRef<WebSocket | null>(null)
  const qc = useQueryClient()
  const { t } = useTranslation()

  useEffect(() => {
    if (!caseId) return

    const cachedItems = (queryKey: unknown[]) => qc.getQueriesData({ queryKey }).flatMap(([, value]) => {
      const data = (value as any)?.data ?? value
      return Array.isArray(data) ? data : []
    })
    const cachedCaseTitle = () => {
      const data = qc.getQueryData<any>(['case', caseId])?.data
      return data?.title || t('caseTasks')
    }
    const sectionName = (sectionId?: string) => {
      const section = cachedItems(['drafts', caseId]).find((item: any) => item.id === sectionId)
      return section?.section_title || t('aiFullDraftRewrite')
    }
    const factName = (factId?: string) => {
      const fact = cachedItems(['facts', caseId]).find((item: any) => item.id === factId)
      return fact?.content?.substring(0, 120) || t('itemFact')
    }

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
            const name = sectionName(data.section_id)
            toast.success(t('fullDraftRewritten'), notificationHistoryMeta({ category: 'agent_draft', type_name: t('agentTaskRewriteSection'), object_name: name }))
            qc.invalidateQueries({ queryKey: ['drafts', caseId] })
            qc.invalidateQueries({ queryKey: ['agentTasks', caseId] })
          } else if (data.type === 'fact_fixed') {
            const name = factName(data.fact_id)
            toast.success('事实更新，相关文案已同步刷新', notificationHistoryMeta({ category: 'fact', type_name: t('facts'), object_name: name }))
            qc.invalidateQueries({ queryKey: ['drafts', caseId] })
          } else if (data.type === 'fact_reparsed') {
            const name = factName(data.fact_id)
            toast.success(t('factDisputeReparsed'), notificationHistoryMeta({ category: 'agent_fact', type_name: t('agentRunCategoryFactReparse'), object_name: name }))
            qc.invalidateQueries({ queryKey: ['facts', caseId] })
            qc.invalidateQueries({ queryKey: ['agentTasks', caseId] })
          } else if (data.type === 'rfi_generated') {
            toast.success('RFI 补件回复已生成', notificationHistoryMeta({ category: 'agent_draft', type_name: t('agentTaskRfiGenerate'), object_name: cachedCaseTitle() }))
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
