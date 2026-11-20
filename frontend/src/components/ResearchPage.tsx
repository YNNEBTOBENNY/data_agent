import { useEffect, useRef, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Form,
  Input,
  Row,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import { api, Datasource } from '../api'

interface RoundResult {
  round_number: number
  question: string
  suggestion: string
  sql: string
  source: string
  columns: string[]
  rows: unknown[][]
  row_count: number
}

export default function ResearchPage({
  datasources,
  seed,
  onBack,
}: {
  datasources: Datasource[]
  seed?: { datasourceId: number; question: string }
  onBack?: () => void
}) {
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [topic, setTopic] = useState('')
  const [rounds, setRounds] = useState<RoundResult[]>([])
  const [currentSuggestion, setCurrentSuggestion] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [summary, setSummary] = useState<null | {
    total_rounds: number
    non_empty_rounds: number
    insufficient: boolean
    conclusions: string[]
    rounds: { round_number: number; question: string; suggestion: string; sql: string; source: string; row_count: number }[]
  }>(null)

  const [form] = Form.useForm()
  const seededRef = useRef(false)

  useEffect(() => {
    if (seed && !seededRef.current) {
      seededRef.current = true
      ;(async () => {
        setError('')
        try {
          const r = await api.createResearch(seed.question, seed.datasourceId)
          setSessionId(r.id)
          setTopic(seed.question)
          const rr = await api.runResearchRound(r.id, seed.question, 'execute')
          setRounds([rr])
          setCurrentSuggestion(rr.suggestion || '')
        } catch (e: any) {
          setError(e?.response?.data?.detail ?? String(e))
        }
      })()
    }
  }, [seed])

  const createSession = async (values: { topic: string; datasource_id: number }) => {
    setError('')
    try {
      const r = await api.createResearch(values.topic, values.datasource_id)
      setSessionId(r.id)
      setTopic(values.topic)
      setRounds([])
      setSummary(null)
      setCurrentSuggestion('')
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e))
    }
  }

  const runRound = async (question: string, action = 'execute') => {
    if (!sessionId) return
    setLoading(true)
    setError('')
    try {
      const r = await api.runResearchRound(sessionId, question, action)
      setRounds((prev) => [...prev, r])
      setCurrentSuggestion(r.suggestion || '')
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e))
    } finally {
      setLoading(false)
    }
  }

  const converge = async () => {
    if (!sessionId) return
    try {
      setSummary(await api.convergeResearch(sessionId))
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e))
    }
  }

  const download = async (format: 'markdown' | 'word') => {
    if (!sessionId) return
    const blob = await api.exportResearch(sessionId, format)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `research_${sessionId}.${format === 'word' ? 'docx' : 'md'}`
    a.click()
    URL.revokeObjectURL(url)
  }

  return (
    <Row gutter={16}>
      <Col span={10}>
        {seed && onBack && (
          <Button onClick={onBack} style={{ marginBottom: 12 }}>← 返回查询</Button>
        )}
        {!seed && (
          <Card title="研究主题" size="small">
            <Form form={form} layout="vertical" onFinish={createSession}>
              <Form.Item label="数据源" name="datasource_id" rules={[{ required: true }]}>
                <Select options={datasources.map((d) => ({ value: d.id, label: `${d.name} (${d.type})` }))} />
              </Form.Item>
              <Form.Item label="研究主题" name="topic" rules={[{ required: true }]}>
                <Input.TextArea rows={2} placeholder="例如：olist 各州营收分析" />
              </Form.Item>
              <Button type="primary" htmlType="submit">
                创建研究
              </Button>
            </Form>
          </Card>
        )}

        {sessionId && (
          <Card title={`当前研究：${topic}`} size="small" style={{ marginTop: 12 }}>
            <Input.TextArea
              rows={2}
              placeholder="输入下一个问题，或采纳下方建议"
              id="round-question"
            />
            <Space style={{ marginTop: 8 }}>
              <Button
                type="primary"
                loading={loading}
                onClick={() => runRound((document.getElementById('round-question') as HTMLTextAreaElement).value)}
              >
                执行
              </Button>
              {currentSuggestion && (
                <Button onClick={() => runRound(currentSuggestion, 'confirm')}>
                  采纳建议
                </Button>
              )}
              <Button onClick={converge}>收敛并生成摘要</Button>
            </Space>
            {currentSuggestion && (
              <Alert style={{ marginTop: 8 }} type="info" message="下一步建议" description={currentSuggestion} />
            )}
          </Card>
        )}

        {error && <Alert type="error" message={error} style={{ marginTop: 12 }} />}
      </Col>

      <Col span={14}>
        <Card title="研究过程" size="small">
          {rounds.length === 0 && !summary && <Typography.Text type="secondary">还没有轮次</Typography.Text>}
          <Collapse
            items={rounds.map((r) => ({
              key: String(r.round_number),
              label: `第 ${r.round_number} 轮 · ${r.question}（${r.row_count} 行 · ${r.source}）`,
              children: (
                <div>
                  <Typography.Text strong>SQL</Typography.Text>
                  <pre style={{ background: '#f6f6f6', padding: 8, borderRadius: 4, overflowX: 'auto' }}>{r.sql}</pre>
                  <Typography.Text strong>结果（前 20 行）</Typography.Text>
                  <pre style={{ background: '#fafafa', padding: 8, maxHeight: 200, overflow: 'auto' }}>
                    {JSON.stringify(r.rows.slice(0, 20), null, 0)}
                  </pre>
                  {r.suggestion && <Alert type="info" message={`建议：${r.suggestion}`} />}
                </div>
              ),
            }))}
          />

          {summary && (
            <Card title="研究摘要" size="small" style={{ marginTop: 16, background: '#f6ffed' }}>
              {summary.insufficient && <Tag color="orange">数据不足，以下为初步判断</Tag>}
              {summary.conclusions.map((c, i) => (
                <Typography.Paragraph key={i}>{c}</Typography.Paragraph>
              ))}
              <Space>
                <Button onClick={() => download('markdown')}>导出 Markdown</Button>
                <Button onClick={() => download('word')}>导出 Word</Button>
              </Space>
            </Card>
          )}
        </Card>
      </Col>
    </Row>
  )
}
