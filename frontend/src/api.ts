import axios from 'axios'

const client = axios.create({ baseURL: '/api' })

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

export interface QueryResult {
  sql: string
  columns: string[]
  rows: unknown[][]
  row_count: number
  truncated: boolean
  source: string
  caliber_source: string
  semantic_model_name: string
  semantic_model_version: number | null
  join_path: string
  corrected: boolean
  correction_count: number
}

export interface Datasource {
  id: number
  name: string
  type: string
  host: string
  port: number
  db_name: string
  timezone?: string
  timezone_verified?: boolean
  status: string
}

export interface SemanticModel {
  id: number
  name: string
  datasource_id: number
  version: number
  status: string
}

export interface ChartRender {
  id: number
  name: string
  chart_type: string
  status: string
  columns?: string[]
  rows?: unknown[][]
  row_count?: number
  error?: string
}

export const api = {
  login: (username: string, password: string) =>
    client.post('/auth/login', null, { params: { username, password } }).then((r) => r.data),

  register: (username: string, password: string, role = 'member') =>
    client.post('/auth/register', null, { params: { username, password, role } }).then((r) => r.data),

  listDatasources: () => client.get<Datasource[]>('/datasources').then((r) => r.data),

  createDatasource: (body: Record<string, unknown>) =>
    client.post('/datasources', body).then((r) => r.data),

  deleteDatasource: (id: number) => client.delete(`/datasources/${id}`).then((r) => r.data),

  collectMetadata: (id: number) => client.post(`/datasources/${id}/collect`).then((r) => r.data),

  verifyTimezone: (id: number) => client.post(`/datasources/${id}/verify-timezone`).then((r) => r.data),

  listSemanticModels: () => client.get<SemanticModel[]>('/semantic').then((r) => r.data),

  getModelFields: (name: string) =>
    client.get<{ measures: string[]; dimensions: string[] }>('/semantic/fields', { params: { name } }).then((r) => r.data),

  query: (question: string, datasourceId: number) =>
    client
      .post<QueryResult>('/query', { question, datasource_id: datasourceId, dialect: 'mysql' })
      .then((r) => r.data),

  agentQuery: (question: string, datasourceId: number) =>
    client
      .post<{
        question: string
        answer: string
        steps: number
        trajectory: { step: number; tool: string; args: Record<string, unknown>; observation: Record<string, unknown> }[]
        result: QueryResult | null
      }>('/agent/query', null, { params: { question, datasource_id: datasourceId } })
      .then((r) => r.data),

  previewChart: (chart: {
    name: string
    chart_type: string
    datasource_id: number
    semantic_model_name: string
    intent: Record<string, unknown>
  }) => client.post('/dashboard/chart/preview', chart).then((r) => r.data),

  createDashboard: (body: {
    name: string
    charts: {
      name: string
      chart_type: string
      datasource_id: number
      semantic_model_name: string
      intent: Record<string, unknown>
    }[]
  }) => client.post('/dashboard', body).then((r) => r.data),

  listDashboards: () => client.get<{ id: number; name: string }[]>('/dashboard').then((r) => r.data),

  openDashboard: (id: number) =>
    client.get<{ id: number; name: string; charts: ChartRender[] }>(`/dashboard/${id}`).then((r) => r.data),

  drillChart: (chartId: number, dimension: string, value: string, baseFilters: Record<string, unknown>[]) =>
    client
      .post<{ dimension: string; filters: Record<string, unknown>[]; sql: string; columns: string[]; rows: unknown[][]; row_count: number }>(
        `/dashboard/chart/${chartId}/drill`,
        { dimension, value, base_filters: baseFilters },
      )
      .then((r) => r.data),

  createResearch: (topic: string, datasourceId: number) =>
    client.post('/research', null, { params: { topic, datasource_id: datasourceId } }).then((r) => r.data),

  runResearchRound: (sessionId: number, question: string, action = 'execute') =>
    client
      .post(`/research/${sessionId}/round`, null, { params: { question, action } })
      .then((r) => r.data),

  convergeResearch: (sessionId: number) =>
    client.post(`/research/${sessionId}/converge`).then((r) => r.data),

  getResearch: (sessionId: number) => client.get(`/research/${sessionId}`).then((r) => r.data),

  exportResearch: (sessionId: number, format: 'markdown' | 'word') =>
    client.get(`/research/${sessionId}/export`, { params: { format }, responseType: 'blob' }).then((r) => r.data),
}
