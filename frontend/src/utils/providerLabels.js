const providerLabels = {
  mock_fallback: {
    short: '本地兜底模型',
    option: '本地兜底模型（仅演示）',
    type: '本地兜底',
    description: '用于无真实模型配置时跑通评测流程，不代表真实模型能力。'
  },
  openai_compatible: {
    short: '真实大模型接口',
    option: '真实大模型接口（兼容格式）',
    type: '真实模型接口',
    description: '通过兼容格式接入外部大模型服务，用于评测真实被测模型。'
  },
  custom_endpoint: {
    short: '自定义模型接口',
    option: '自定义模型接口',
    type: '自定义接口',
    description: '接入团队自建服务、企业内部模型或其他外部被测模型接口。'
  }
}

const legacyProviderMap = {
  mock_baseline: 'mock_fallback',
  mock_strong: 'mock_fallback'
}

export const normalizeProvider = (provider) => legacyProviderMap[provider] || provider || 'mock_fallback'

export const providerDisplayName = (provider) => {
  if (!provider) return '-'
  const normalized = normalizeProvider(provider)
  return providerLabels[normalized]?.short || provider || '-'
}

export const providerOptionLabel = (provider) => {
  if (!provider) return '-'
  const normalized = normalizeProvider(provider)
  return providerLabels[normalized]?.option || providerDisplayName(provider)
}

export const providerDescription = (provider, fallback = '') => {
  if (!provider) return fallback || '-'
  const normalized = normalizeProvider(provider)
  return providerLabels[normalized]?.description || fallback || '-'
}

export const providerTypeLabel = (provider, fallback = '') => {
  if (!provider) return fallback || '-'
  const normalized = normalizeProvider(provider)
  return providerLabels[normalized]?.type || fallback || '-'
}

export const PROVIDER_OPTIONS = Object.keys(providerLabels).map((value) => ({
  value,
  label: providerLabels[value].option
}))
