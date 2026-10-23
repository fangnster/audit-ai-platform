type LlmAction = 'test' | 'parse' | 'translate' | 'generate' | 'rewrite'

const ACTION_ZH: Record<LlmAction, string> = {
  test: '测试生成',
  parse: '文件解析',
  translate: '翻译',
  generate: '审计底稿生成',
  rewrite: '审计底稿重写',
}

const ACTION_EN: Record<LlmAction, string> = {
  test: 'Generation test',
  parse: 'Document parsing',
  translate: 'Translation',
  generate: 'Audit draft generation',
  rewrite: 'Audit draft rewrite',
}

function detailToText(error: any) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(item => item?.msg || item).join(' ')
  if (detail && typeof detail === 'object') return JSON.stringify(detail)
  return error?.message || ''
}

export function readableLlmError(error: any, language = 'zh', action: LlmAction = 'generate') {
  const zh = language.startsWith('zh')
  const status = Number(error?.response?.status || 0)
  const text = detailToText(error).toLowerCase()
  const upstreamStatus = Number(text.match(/(?:llm\s*)?http\s*(\d{3})/)?.[1] || 0)
  const effectiveStatus = upstreamStatus || status
  const actionName = zh ? ACTION_ZH[action] : ACTION_EN[action]
  const prefix = zh ? `${actionName}失败。` : `${actionName} failed. `
  const checkSettings = zh
    ? '请检查已保存的接口地址、模型名称和 API Key 后重试。'
    : 'Please check the saved base URL, model name, and API key, then try again.'

  if (effectiveStatus === 401 || effectiveStatus === 403 || /unauthorized|forbidden|invalid api key|api key|authentication|permission|credentials/.test(text)) {
    return zh
      ? `${prefix}API Key 无效、权限不足，或账号/额度不可用。${checkSettings}`
      : `${prefix}The API key is invalid, lacks permission, or the account/quota is unavailable. ${checkSettings}`
  }

  if (effectiveStatus === 404 || /not found|model.*not.*found|unknown model|invalid model/.test(text)) {
    return zh
      ? `${prefix}接口地址或模型名称可能不匹配。${checkSettings}`
      : `${prefix}The base URL or model name may not match the provider. ${checkSettings}`
  }

  if (effectiveStatus === 408 || effectiveStatus === 504 || /timeout|timed out|readtimeout|connecttimeout/.test(text)) {
    return zh
      ? `${prefix}大模型服务响应超时。请稍后重试，或检查接口地址是否可访问。`
      : `${prefix}The model service timed out. Try again later, or check whether the base URL is reachable.`
  }

  if (effectiveStatus === 429 || /rate limit|too many requests|quota|insufficient balance|billing|余额|额度/.test(text)) {
    return zh
      ? `${prefix}调用频率、额度或余额不足。请检查供应商控制台后重试。`
      : `${prefix}The provider reported a rate limit, quota, or billing issue. Check the provider console and try again.`
  }

  if (effectiveStatus >= 500 || /bad gateway|service unavailable|internal server error|upstream|provider/.test(text)) {
    return zh
      ? `${prefix}大模型服务暂时不可用。请稍后重试，或切换可用的模型服务。`
      : `${prefix}The model service is temporarily unavailable. Try again later or switch to another model service.`
  }

  if (/base url|url must start|unsupported protocol|invalid url/.test(text)) {
    return zh
      ? `${prefix}接口地址格式不正确，需要填写完整的 http:// 或 https:// 地址。`
      : `${prefix}The base URL format is invalid. Enter a full http:// or https:// URL.`
  }

  if (/not configured|must be saved|required|missing|未保存/.test(text)) {
    return zh
      ? `${prefix}大模型配置还不完整。${checkSettings}`
      : `${prefix}The model configuration is incomplete. ${checkSettings}`
  }

  if (/invalid llm response|empty content|no visible content|json|parse/.test(text)) {
    return zh
      ? `${prefix}大模型返回了无法使用的内容。请换一个更稳定的模型，或调整模型名称后重试。`
      : `${prefix}The model returned unusable content. Try a more stable model or adjust the model name.`
  }

  if (/network error|failed to fetch|connection|connect|dns|name resolution/.test(text)) {
    return zh
      ? `${prefix}无法连接到大模型服务。请检查接口地址和网络后重试。`
      : `${prefix}Could not connect to the model service. Check the base URL and network, then try again.`
  }

  return zh
    ? `${prefix}大模型没有返回可用结果。${checkSettings}`
    : `${prefix}The model did not return a usable result. ${checkSettings}`
}
