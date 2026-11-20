import { useEffect, useState } from 'react'
import { Alert, Button, Card, Form, Input, Select, Space, Switch, Table, Tabs, Tag, Typography } from 'antd'
import { api, Datasource, QueryResult } from './api'
import DashboardPage from './components/DashboardPage'
import ResearchPage from './components/ResearchPage'
import DataSourcePage from './components/DataSourcePage'

interface AgentTrajectory {
  step: number
  tool: string
  args: Record<string, unknown>
  observation: Record<string, unknown>
}

interface AgentResult {
  question: string
  answer: string
  steps: number
  trajectory: AgentTrajectory[]
  result: QueryResult | null
}

export default function App() {
  const [token, setToken] = useState(localStorage.getItem('token'))
  const [datasources, setDatasources] = useState<Datasource[]>([])
  const [result, setResult] = useState<QueryResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [research, setResearch] = useState<{ datasourceId: number; question: string } | null>(null)

  useEffect(() => {
    if (token) api.listDatasources().then(setDatasources).catch(() => {})
  }, [token])

  if (!token) return <LoginPage onLogin={setToken} />

  if (research) {
    return (
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: 24 }}>
        <Typography.Title level={4} style={{ marginTop: 0 }}>Data Agent · 研究</Typography.Title>
        <ResearchPage datasources={datasources} seed={research} onBack={() => setResearch(null)} />
      </div>
    )
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: 24 }}>
      <Typography.Title level={4} style={{ marginTop: 0 }}>
        Data Agent
      </Typography.Title>
      <Tabs
        items={[
          {
            key: 'query',
            label: '查询',
            children: <QueryTab datasources={datasources} result={result} setResult={setResult} loading={loading} setLoading={setLoading} error={error} setError={setError} onResearch={(q, dsId) => setResearch({ datasourceId: dsId, question: q })} />,
          },
          { key: 'dashboard', label: '看板', children: <DashboardPage /> },
          { key: 'admin', label: '管理', children: <DataSourcePage /> },
        ]}
      />
    </div>
  )
}

function QueryTab({
  datasources, result, setResult, loading, setLoading, error, setError, onResearch,
}: {
  datasources: Datasource[]
  result: QueryResult | null
  setResult: (r: QueryResult | null) => void
  loading: boolean
  setLoading: (b: boolean) => void
  error: string
  setError: (e: string) => void
  onResearch: (q: string, dsId: number) => void
}) {
  const [agentMode, setAgentMode] = useState(false)
  const [agentResult, setAgentResult] = useState<AgentResult | null>(null)
  const [lastQuery, setLastQuery] = useState<{ question: string; dsId: number } | null>(null)

  const onQuery = async (question: string, dsId: number, useAgent: boolean) => {
    setLoading(true)
    setError('')
    setAgentResult(null)
    setLastQuery({ question, dsId })
    try {
      if (useAgent) {
        const r = await api.agentQuery(question, dsId)
        setAgentResult(r)
        setResult(r.result)
      } else {
        setResult(await api.query(question, dsId))
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e))
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Card>
        <QueryForm
          datasources={datasources}
          onQuery={onQuery}
          loading={loading}
          agentMode={agentMode}
          setAgentMode={setAgentMode}
        />
      </Card>

      {error && <Alert type="error" message={error} style={{ marginTop: 16 }} />}

      {agentResult && (
        <Card title="Agent 轨迹" size="small" style={{ marginTop: 16, background: '#f0f5ff' }}>
          <Typography.Paragraph>
            <Tag color="blue">共 {agentResult.steps} 步</Tag> {agentResult.answer}
          </Typography.Paragraph>
          {agentResult.trajectory.map((t) => (
            <div key={t.step} style={{ marginBottom: 8 }}>
              <Tag color="geekblue">步骤 {t.step}</Tag>
              <Tag>{t.tool}</Tag>
              {t.observation?.ok === true ? (
                <Typography.Text type="secondary">
                  {t.observation?.row_count != null ? `返回 ${t.observation.row_count} 行` : '成功'}
                </Typography.Text>
              ) : t.observation?.error ? (
                <Typography.Text type="danger">{String(t.observation.error).slice(0, 80)}</Typography.Text>
              ) : t.tool === 'ask_user' ? (
                <Typography.Text>追问：{String(t.observation?.clarify || '')}</Typography.Text>
              ) : null}
            </div>
          ))}
        </Card>
      )}

      {result && (
        <Card title="查询结果" style={{ marginTop: 16 }}>
          <Typography.Paragraph>
            语义模型：<Typography.Text code>{result.semantic_model_name}</Typography.Text> v
            {result.semantic_model_version} · 来源：
            <Typography.Text code>{result.source}</Typography.Text> · 口径：
            {result.caliber_source}
            {result.corrected && ` · 已自动纠错 ${result.correction_count} 次`}
          </Typography.Paragraph>
          <Typography.Text strong>SQL</Typography.Text>
          <pre style={{ background: '#f6f6f6', padding: 12, borderRadius: 6, overflowX: 'auto' }}>
            {result.sql}
          </pre>
          <Typography.Text strong>结果（{result.row_count} 行{result.truncated ? '，已截断' : ''}）</Typography.Text>
          <Table
            style={{ marginTop: 8 }}
            size="small"
            bordered
            dataSource={result.rows.map((row, i) => ({ key: i, ...rowToObj(result.columns, row) }))}
            columns={result.columns.map((c) => ({ title: c, dataIndex: c }))}
            pagination={{ pageSize: 50 }}
            scroll={{ x: 'max-content' }}
          />
          {lastQuery && (
            <Button type="dashed" style={{ marginTop: 12 }} onClick={() => onResearch(lastQuery.question, lastQuery.dsId)}>
              继续研究这个问题 →
            </Button>
          )}
        </Card>
      )}
    </>
  )
}

function rowToObj(columns: string[], row: unknown[]) {
  const obj: Record<string, unknown> = {}
  columns.forEach((c, i) => (obj[c] = row[i]))
  return obj
}

function QueryForm({
  datasources,
  onQuery,
  loading,
  agentMode,
  setAgentMode,
}: {
  datasources: Datasource[]
  onQuery: (q: string, dsId: number, useAgent: boolean) => void
  loading: boolean
  agentMode: boolean
  setAgentMode: (b: boolean) => void
}) {
  const [form] = Form.useForm()
  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={(v) => onQuery(v.question, v.datasource_id, agentMode)}
      initialValues={{ datasource_id: datasources[0]?.id }}
    >
      <Form.Item label="数据源" name="datasource_id" rules={[{ required: true }]}>
        <Select
          options={datasources.map((d) => ({ value: d.id, label: `${d.name} (${d.type})` }))}
          placeholder="选择数据源"
        />
      </Form.Item>
      <Form.Item label="用自然语言提问" name="question" rules={[{ required: true }]}>
        <Input.TextArea rows={2} placeholder="例如：各卖家州的营收是多少？" />
      </Form.Item>
      <Space>
        <Button type="primary" htmlType="submit" loading={loading}>
          查询
        </Button>
        <Space size={4}>
          <Switch checked={agentMode} onChange={setAgentMode} size="small" />
          <Typography.Text type="secondary">Agent 模式（自主决策 + 轨迹可见）</Typography.Text>
        </Space>
      </Space>
    </Form>
  )
}

function LoginPage({ onLogin }: { onLogin: (token: string) => void }) {
  const [err, setErr] = useState('')
  return (
    <div style={{ maxWidth: 400, margin: '120px auto', padding: 24 }}>
      <Typography.Title level={3}>Data Agent 登录</Typography.Title>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Input id="u" placeholder="用户名" defaultValue="admin" />
        <Input.Password id="p" placeholder="密码" defaultValue="admin123" />
        {err && <Alert type="error" message={err} />}
        <Button
          type="primary"
          block
          onClick={async () => {
            const u = (document.getElementById('u') as HTMLInputElement).value
            const p = (document.getElementById('p') as HTMLInputElement).value
            try {
              const r = await api.login(u, p)
              localStorage.setItem('token', r.token)
              onLogin(r.token)
            } catch (e: any) {
              setErr(e?.response?.data?.detail ?? String(e))
            }
          }}
        >
          登录
        </Button>
      </Space>
    </div>
  )
}
