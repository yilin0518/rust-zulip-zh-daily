import { cpSync, existsSync } from 'node:fs'

if (!existsSync('site/data/meta.json')) {
  throw new Error(
    '缺少站点数据。请先运行 python scripts/pipeline.py 或 python scripts/make_sample_data.py',
  )
}
cpSync('site/data', 'dist/data', { recursive: true })
