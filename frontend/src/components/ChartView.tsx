import ReactECharts from 'echarts-for-react'
import { Table } from 'antd'
import type { ChartRender } from '../api'

export default function ChartView({
  chart,
  onDrill,
}: {
  chart: ChartRender
  onDrill?: (dimension: string, value: string) => void
}) {
  if (chart.status !== 'active' || !chart.columns || !chart.rows) {
    return <div style={{ color: '#999' }}>{chart.error || '数据不可用'}</div>
  }

  const { columns, rows } = chart
  if (columns.length === 0 || rows.length === 0) {
    return <div style={{ color: '#999' }}>无数据</div>
  }

  // 约定：最后一列是维度（x 轴），其余列是度量（series）
  const dimIdx = columns.length - 1
  const measureIdx = Array.from({ length: dimIdx }, (_, i) => i)
  const dimName = columns[dimIdx]

  const categories = rows.map((r) => String(r[dimIdx]))

  const handleClick = (params: any) => {
    if (onDrill && params.name != null) {
      onDrill(dimName, String(params.name))
    }
  }

  if (chart.chart_type === 'table') {
    return (
      <Table
        size="small"
        bordered
        dataSource={rows.map((row, i) => {
          const obj: Record<string, unknown> = { key: i }
          columns.forEach((c, j) => (obj[c] = row[j]))
          return obj
        })}
        columns={columns.map((c) => ({ title: c, dataIndex: c }))}
        pagination={{ pageSize: 20 }}
        scroll={{ x: 'max-content' }}
      />
    )
  }

  if (chart.chart_type === 'pie') {
    const option = {
      tooltip: { trigger: 'item' },
      legend: { type: 'scroll', orient: 'vertical', right: 10, top: 20 },
      series: [
        {
          name: columns[0],
          type: 'pie',
          radius: '55%',
          data: rows.map((r) => ({ name: String(r[dimIdx]), value: Number(r[0]) })),
        },
      ],
    }
    return <ReactECharts option={option} style={{ height: 320 }} onEvents={onDrill ? { click: handleClick } : {}} />
  }

  // bar / line
  const option = {
    tooltip: { trigger: 'axis' },
    legend: { data: measureIdx.map((i) => columns[i]) },
    grid: { left: 40, right: 20, top: 40, bottom: 40 },
    xAxis: { type: 'category', data: categories, axisLabel: { rotate: 30 } },
    yAxis: { type: 'value' },
    series: measureIdx.map((i) => ({
      name: columns[i],
      type: chart.chart_type === 'line' ? 'line' : 'bar',
      data: rows.map((r) => Number(r[i])),
    })),
  }
  return <ReactECharts option={option} style={{ height: 320 }} onEvents={onDrill ? { click: handleClick } : {}} />
}
