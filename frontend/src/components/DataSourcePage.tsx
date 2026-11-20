import { useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  message,
} from 'antd'
import { api, Datasource } from '../api'

export default function DataSourcePage() {
  const [datasources, setDatasources] = useState<Datasource[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [type, setType] = useState('mysql')
  const [error, setError] = useState('')

  const load = () => api.listDatasources().then(setDatasources)
  useEffect(() => {
    load()
  }, [])

  const onCreate = async (values: any) => {
    setError('')
    try {
      await api.createDatasource(values)
      message.success('数据源已创建，记得点「采集元数据」')
      setModalOpen(false)
      form.resetFields()
      load()
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? String(e))
    }
  }

  const onCollect = async (id: number) => {
    try {
      const r = await api.collectMetadata(id)
      message.success(`采集完成，共 ${r.collected_tables} 张表`)
      load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail ?? String(e))
    }
  }

  const onVerifyTz = async (id: number) => {
    try {
      await api.verifyTimezone(id)
      message.success('时区已确认')
      load()
    } catch (e: any) {
      message.error(e?.response?.data?.detail ?? String(e))
    }
  }

  const columns = [
    { title: '名称', dataIndex: 'name' },
    {
      title: '类型',
      dataIndex: 'type',
      render: (t: string) => <Tag color={t === 'mysql' ? 'blue' : 'purple'}>{t}</Tag>,
    },
    { title: '地址', dataIndex: 'host', render: (h: string) => h || '-' },
    { title: '库名', dataIndex: 'db_name', render: (d: string) => d || '-' },
    {
      title: '时区',
      render: (_: any, r: Datasource) =>
        r.timezone_verified ? (
          <Tag color="green">{r.timezone} 已确认</Tag>
        ) : (
          <Tag color="orange">{r.timezone} 未确认</Tag>
        ),
    },
    {
      title: '操作',
      render: (_: any, r: Datasource) => (
        <Space>
          <Button size="small" onClick={() => onCollect(r.id)}>采集元数据</Button>
          {!r.timezone_verified && (
            <Button size="small" onClick={() => onVerifyTz(r.id)}>确认时区</Button>
          )}
          <Popconfirm title="确定删除？会连同其元数据一起删除" onConfirm={async () => { await api.deleteDatasource(r.id); message.success('已删除'); load() }}>
            <Button size="small" danger>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div>
      <Card
        title="数据源管理（管理员）"
        size="small"
        extra={<Button type="primary" onClick={() => setModalOpen(true)}>新增数据源</Button>}
      >
        <Table rowKey="id" size="small" columns={columns} dataSource={datasources} pagination={false} />
      </Card>

      <Modal title="新增数据源" open={modalOpen} onCancel={() => setModalOpen(false)} onOk={() => form.submit()} okText="创建">
        <Form form={form} layout="vertical" onFinish={onCreate} initialValues={{ type: 'mysql', timezone: 'UTC', db_name: '' }}>
          <Form.Item label="类型" name="type" rules={[{ required: true }]}>
            <Select
              onChange={(v) => setType(v)}
              options={[
                { value: 'mysql', label: 'MySQL' },
                { value: 'postgres', label: 'PostgreSQL' },
              ]}
            />
          </Form.Item>
          <Form.Item label="名称" name="name" rules={[{ required: true }]}>
            <Input placeholder="如 my_orders" />
          </Form.Item>
          <Form.Item label="主机" name="host"><Input placeholder="127.0.0.1" /></Form.Item>
          <Form.Item label="端口" name="port"><InputNumber style={{ width: '100%' }} placeholder={type === 'mysql' ? '3306' : '5432'} /></Form.Item>
          <Form.Item label="库名" name="db_name"><Input placeholder="库名" /></Form.Item>
          <Form.Item label="只读账号" name="readonly_user"><Input placeholder="readonly" /></Form.Item>
          <Form.Item label="只读密码" name="readonly_password"><Input.Password /></Form.Item>
          <Form.Item label="时区" name="timezone"><Input placeholder="UTC" /></Form.Item>
          {error && <Alert type="error" message={error} />}
        </Form>
      </Modal>
    </div>
  )
}
