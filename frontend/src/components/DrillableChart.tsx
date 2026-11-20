import { useState } from 'react'
import { Breadcrumb, Tag } from 'antd'
import { api, ChartRender } from '../api'
import ChartView from './ChartView'

interface DrillEntry {
  label: string
  view: ChartRender
  filters: Record<string, unknown>[]
}

export default function DrillableChart({ chart }: { chart: ChartRender }) {
  const [history, setHistory] = useState<DrillEntry[]>([{ label: '全部', view: chart, filters: [] }])
  const [current, setCurrent] = useState(0)

  const onDrill = async (dimension: string, value: string) => {
    const baseFilters = history[current].filters
    try {
      const r = await api.drillChart(chart.id, dimension, value, baseFilters)
      const newView: ChartRender = {
        id: chart.id,
        name: `${chart.name} / ${value}`,
        chart_type: chart.chart_type,
        status: 'active',
        columns: r.columns,
        rows: r.rows,
        row_count: r.row_count,
      }
      const newEntry: DrillEntry = {
        label: value,
        view: newView,
        filters: [...baseFilters, { field: dimension, op: '=', value }],
      }
      const next = [...history.slice(0, current + 1), newEntry]
      setHistory(next)
      setCurrent(next.length - 1)
    } catch (e: any) {
      console.error('下钻失败', e)
    }
  }

  const items = history.map((h, i) => ({
    title: (
      <a
        key={i}
        onClick={() => setCurrent(i)}
        style={i === current ? { fontWeight: 700 } : undefined}
      >
        {h.label}
      </a>
    ),
  }))

  return (
    <div>
      <Breadcrumb items={items} style={{ marginBottom: 8 }} />
      <ChartView chart={history[current].view} onDrill={onDrill} />
      {history.length > 1 && <Tag color="blue">已下钻 {history.length - 1} 层，点面包屑可回退</Tag>}
    </div>
  )
}
