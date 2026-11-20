import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  List,
  Row,
  Select,
  Space,
  Typography,
} from 'antd'
import { api, Datasource, SemanticModel, ChartRender } from '../api'
import ChartView from './ChartView'
import DrillableChart from './DrillableChart'

export default function DashboardPage() {
  const [datasources, setDatasources] = useState<Datasource[]>([])
  const [models, setModels] = useState<SemanticModel[]>([])
  const [dashboards, setDashboards] = useState<{ id: number; name: string }[]>([])
  const [current, setCurrent] = useState<{ id: number; name: string; charts: ChartRender[] } | null>(null)
  const [preview, setPreview] = useState<ChartRender | null>(null)
  const [fields, setFields] = useState<{ measures: string[]; dimensions: string[] } | null>(null)

  const [form] = Form.useForm()
  const dsId = Form.useWatch('datasource_id', form)
  const modelName = Form.useWatch('semantic_model_name', form)
  const measures = Form.useWatch('measures', form)
  const dimensions = Form.useWatch('dimensions', form)

  // 图表类型自动推荐：按维度/度量数量给默认值，用户仍可手动改
  useEffect(() => {
    const m = measures as unknown[] | undefined
    const d = dimensions as unknown[] | undefined
    if (!m?.length) return
    if (!d?.length) {
      form.setFieldValue('chart_type', 'table')
    } else if (d.length === 1 && m.length === 1) {
      form.setFieldValue('chart_type', 'bar')
    } else if (d.length >= 1) {
      form.setFieldValue('chart_type', 'bar')
    }
  }, [measures, dimensions, form])

  const load = () => {
    api.listDatasources().then(setDatasources)
    api.listSemanticModels().then(setModels)
    api.listDashboards().then(setDashboards)
  }

  useEffect(load, [])

  useEffect(() => {
    if (modelName) {
      api
        .listSemanticModels()
        .then(() => api.getModelFields(modelName))
        .then(setFields)
        .catch(() => setFields(null))
    } else {
      setFields(null)
    }
  }, [modelName])

  const modelOptions = models
    .filter((m) => !dsId || m.datasource_id === dsId)
    .map((m) => ({ value: m.name, label: `${m.name} (v${m.version})` }))

  const onPreview = async (values: any) => {
    const chart = {
      name: values.name || '预览图表',
      chart_type: values.chart_type,
      datasource_id: values.datasource_id,
      semantic_model_name: values.semantic_model_name,
      intent: {
        measures: values.measures.split(/[,，]/).map((s: string) => s.trim()),
        dimensions: values.dimensions ? values.dimensions.split(/[,，]/).map((s: string) => s.trim()) : [],
      },
    }
    const r = await api.previewChart(chart)
    setPreview({ id: 0, name: chart.name, chart_type: chart.chart_type, status: 'active', ...r })
  }

  const onSave = async (values: any) => {
    const charts = [
      {
        name: values.name || '图表1',
        chart_type: values.chart_type,
        datasource_id: values.datasource_id,
        semantic_model_name: values.semantic_model_name,
        intent: {
          measures: values.measures.split(/[,，]/).map((s: string) => s.trim()),
          dimensions: values.dimensions ? values.dimensions.split(/[,，]/).map((s: string) => s.trim()) : [],
        },
      },
    ]
    await api.createDashboard({ name: values.dashboard_name || '我的看板', charts })
    load()
  }

  return (
    <Row gutter={16}>
      <Col span={9}>
        <Card title="空态配置（不拉业务数据建图）" size="small">
          <Form form={form} layout="vertical" onFinish={onPreview}>
            <Form.Item label="数据源" name="datasource_id" rules={[{ required: true }]}>
              <Select options={datasources.map((d) => ({ value: d.id, label: `${d.name} (${d.type})` }))} />
            </Form.Item>
            <Form.Item label="语义模型" name="semantic_model_name" rules={[{ required: true }]}>
              <Select options={modelOptions} />
            </Form.Item>
            <Form.Item label="度量（逗号分隔）" name="measures" rules={[{ required: true }]}>
              <Select mode="tags" placeholder={fields?.measures.join(', ') || '输入度量名'} options={(fields?.measures || []).map((m) => ({ value: m, label: m }))} />
            </Form.Item>
            <Form.Item label="维度（逗号分隔，可空）" name="dimensions">
              <Select mode="tags" placeholder={fields?.dimensions.join(', ') || '输入维度名'} options={(fields?.dimensions || []).map((d) => ({ value: d, label: d }))} />
            </Form.Item>
            <Form.Item label="图表类型" name="chart_type" initialValue="bar" rules={[{ required: true }]}>
              <Select options={[
                { value: 'bar', label: '柱状图' },
                { value: 'line', label: '折线图' },
                { value: 'pie', label: '饼图' },
                { value: 'table', label: '数据表格' },
              ]} />
            </Form.Item>
            <Form.Item label="图表名称" name="name">
              <Input placeholder="图表名称" />
            </Form.Item>
            <Form.Item label="看板名称" name="dashboard_name">
              <Input placeholder="保存到的看板名称" />
            </Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">预览</Button>
              <Button onClick={() => form.validateFields().then(onSave)}>保存到看板</Button>
            </Space>
          </Form>
        </Card>
      </Col>

      <Col span={15}>
        <Card title="看板" size="small">
          <List
            size="small"
            dataSource={dashboards}
            renderItem={(d) => (
              <List.Item
                actions={[<a key="open" onClick={() => api.openDashboard(d.id).then(setCurrent)}>打开</a>]}
              >
                {d.name}
              </List.Item>
            )}
          />
          {current && (
            <div style={{ marginTop: 16 }}>
              <Typography.Title level={5}>{current.name}</Typography.Title>
              {current.charts.length === 0 && <Empty description="看板暂无图表" />}
              {current.charts.map((c) => (
                <Card key={c.id} title={`${c.name}（${c.chart_type}）`} size="small" style={{ marginBottom: 12 }}>
                  {c.status !== 'active' ? (
                    <Alert type="error" message={c.error || '图表失效'} />
                  ) : (
                    <DrillableChart chart={c} />
                  )}
                </Card>
              ))}
            </div>
          )}
        </Card>

        {preview && (
          <Card title={`预览：${preview.name}`} size="small" style={{ marginTop: 16 }}>
            <ChartView chart={preview} />
          </Card>
        )}
      </Col>
    </Row>
  )
}
