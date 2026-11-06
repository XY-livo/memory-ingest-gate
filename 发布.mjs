#!/usr/bin/env node
// 发布到 GitHub（内容 API 上传 + 开 Issues）
import fs from 'node:fs'
import path from 'node:path'
const TOKEN = process.env.GH_TOKEN
const REPO = process.env.REPO || 'memory-ingest-gate'
const API = 'https://api.github.com'
const H = { Authorization: 'Bearer ' + TOKEN, Accept: 'application/vnd.github+json', 'User-Agent': 'publish', 'Content-Type': 'application/json' }
async function api(m, u, b) {
  const r = await fetch(API + u, { method: m, headers: H, body: b ? JSON.stringify(b) : undefined })
  const t = await r.text(); let j = null; try { j = t ? JSON.parse(t) : null } catch {}
  return { status: r.status, json: j, text: t }
}
const me = (await api('GET', '/user')).json
const login = me.login
let r = await api('GET', `/repos/${login}/${REPO}`)
if (r.status === 404) {
  r = await api('POST', '/user/repos', { name: REPO, private: false, auto_init: true, description: '入库闸门：给 AI 记忆库用的写入闸（校验→重复→冲突→用途→等级分流）', homepage: '' })
  console.log('建仓：', r.status)
}
const files = []
const walk = (d) => { for (const e of fs.readdirSync(d, { withFileTypes: true })) { if (e.name === 'node_modules' || e.name.startsWith('.')) continue; const p = path.join(d, e.name); e.isDirectory() ? walk(p) : files.push(p) } }
walk('.')
for (const f of files) {
  const rel = path.relative('.', f).replace(/\\/g, '/')
  const content = fs.readFileSync(f).toString('base64')
  const cur = await api('GET', `/repos/${login}/${REPO}/contents/${encodeURIComponent(rel)}`)
  const sha = cur.json && cur.json.sha
  const put = await api('PUT', `/repos/${login}/${REPO}/contents/${encodeURIComponent(rel)}`, { message: (sha ? 'update ' : 'add ') + rel, content, branch: 'main', ...(sha ? { sha } : {}) })
  console.log(put.status < 400 ? '✓ ' + rel : '✗ ' + rel + ' ' + put.status)
}
console.log('https://github.com/' + login + '/' + REPO)
