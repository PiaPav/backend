import { mkdir, readFile, readdir, rename, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'

// OpenCode V1 plugin. No dependencies and no additional model calls.
const BUDGET_TOKENS = 4000
const MAX_HANDOFFS = 3
const ROLES = new Set(['orchestrator', 'architect', 'coder', 'tester', 'reviewer', 'math_reviever'])
const DELEGATE = new Set(['task', 'delegate_task', 'subagent'])
const WRITES = new Set(['write', 'edit', 'apply_patch', 'patch', 'multiedit'])
const REDACT = /(?:sk-[\w-]{12,}|gh[pousr]_[\w-]{12,}|github_pat_[\w-]{12,}|AKIA[0-9A-Z]{16}|Bearer\s+[\w.\-]{12,}|(?:api[_-]?key|access[_-]?token|secret|password|authorization)\s*[:=]\s*[^\s,;]+)/gi
const HANDOFF_START = '<session-handoff>'
const HANDOFF_END = '</session-handoff>'
const CONTEXT_PATTERN = /\s*<session-memory-context>[\s\S]*?<\/session-memory-context>/g
const HANDOFF_INSTRUCTION = 'Заверши ответ блоком <session-handoff> ... </session-handoff> с разделами: Результат, Изменённые файлы, Решения, Проверки, Следующий шаг. Не утверждай о проверках, которые не запускал.'
const APPROX_CHARS_PER_TOKEN = 3 // conservative for mixed Russian/code content, not exact tokenizer
const MAX_CONTEXT_CHARS = BUDGET_TOKENS * APPROX_CHARS_PER_TOKEN
const MAX_RECORD_CHARS = 2800
const MAX_FILES = 24

const scrub = (s) => String(s ?? '').replace(REDACT, '[REDACTED]').replace(/\u0000/g, '')
const truncate = (s, n) => { const x = scrub(s); return x.length > n ? x.slice(0, n - 1) + '…' : x }
const unwrap = (v) => v?.data ?? v
const textOf = (message) => (message?.parts ?? []).filter(x => x?.type === 'text' && !x.synthetic).map(x => x.text ?? '').join('\n')
const safeName = (s) => String(s).replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 90)
const basename = (p) => String(p ?? '').replaceAll('\\', '/').split('/').slice(-3).join('/')
const defaultSession = '# Состояние сессии\n\nНет подтверждённых завершённых вызовов.\n'
const emptyDecisions = '# Решения\n\nЗдесь фиксируются решения, явно указанные в handoff агентов.\n'

export const SessionMemory = async ({ directory, client }) => {
  const root = resolve(directory, '.opencode', 'memory', 'sessions')
  const pending = new Map()
  const parents = new Map()
  const roles = new Map()
  const calls = new Map()
  const queues = new Map()
  const seen = new Set()
  const childCalls = new Map()
  const diagnostics = async (err) => {
    try { await client.app.log({ body: { service: 'session-memory', level: 'warn', message: truncate(err, 500) } }) } catch {}
  }
  function serialize(id, work) {
    const prev = queues.get(id) ?? Promise.resolve()
    const next = prev.catch(() => {}).then(work)
    queues.set(id, next)
    void next.finally(() => { if (queues.get(id) === next) queues.delete(id) }).catch(() => {})
    return next
  }
  async function atomic(path, text) {
    const tmp = `${path}.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`
    await writeFile(tmp, text, { mode: 0o600 })
    await rename(tmp, path)
  }
  async function read(path, max = 16000) {
    try { return truncate(await readFile(path, 'utf8'), max) } catch (e) { if (e?.code === 'ENOENT') return ''; throw e }
  }
  async function info(id) {
    const response = unwrap(await client.session.get({ path: { id } }))
    if (response?.parentID) parents.set(id, response.parentID)
    return response
  }
  async function rootId(id) {
    let cursor = id
    const visited = new Set()
    for (let depth = 0; depth < 16 && cursor && !visited.has(cursor); depth++) {
      visited.add(cursor)
      let parent = parents.get(cursor)
      if (!parent) {
        const s = await info(cursor)
        parent = s?.parentID
      }
      if (!parent) return cursor
      cursor = parent
    }
    return cursor || id
  }
  // Readable directories are keyed by root-session creation time, not generated title.
  // Keep the OpenCode session ID in a short suffix, and reuse legacy folders.
  const folders = new Map()
  function timestamp(ms) {
    const d = new Date(Number.isFinite(ms) ? ms : Date.now())
    const pad = n => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}`
  }
  async function folder(rootSession) {
    if (folders.has(rootSession)) return folders.get(rootSession)
    const legacy = join(root, safeName(rootSession))
    const entries = await readdir(root, { withFileTypes: true }).catch(e => {
      if (e?.code === 'ENOENT') return []
      throw e
    })
    // Existing session folders retain their location after a plugin upgrade.
    if (entries.some(e => e.isDirectory() && e.name === safeName(rootSession))) {
      folders.set(rootSession, legacy)
      return legacy
    }
    const suffix = safeName(rootSession).slice(-12)
    const existing = entries.find(e => e.isDirectory() && e.name.endsWith(`--${suffix}`))
    if (existing) {
      const found = join(root, existing.name)
      folders.set(rootSession, found)
      return found
    }
    const session = await info(rootSession)
    const created = session?.time?.created
    if (!Number.isFinite(created)) {
      // A stable name requires a stable timestamp. Use the legacy ID until available.
      folders.set(rootSession, legacy)
      return legacy
    }
    const named = join(root, `${timestamp(created)}--${suffix}`)
    folders.set(rootSession, named)
    return named
  }
  async function ensure(id) {
    const dir = await folder(id)
    await mkdir(join(dir, 'agents'), { recursive: true })
    await mkdir(join(dir, 'handoffs'), { recursive: true })
    return dir
  }
  async function listHandoffs(dir) {
    try { return (await readdir(join(dir, 'handoffs'))).filter(f => /^\d+-[\w-]+\.md$/.test(f)).sort() } catch (e) { if (e?.code === 'ENOENT') return []; throw e }
  }
  const roleOf = (args) => {
    const name = args?.subagent_type ?? args?.agent ?? args?.subagentType
    return ROLES.has(name) ? name : null
  }
  function summarizeText(raw) {
    const marker = raw.lastIndexOf(HANDOFF_START)
    if (marker >= 0) {
      const end = raw.indexOf(HANDOFF_END, marker)
      if (end > marker) return truncate(raw.slice(marker + HANDOFF_START.length, end).trim(), MAX_RECORD_CHARS)
    }
    return truncate(raw.trim() || 'Смысловой отчёт отсутствует.', 1400)
  }
  function extractDecisions(text) {
    const m = text.match(/(?:^|\n)#{1,4}\s*(?:Решения|Принятые решения|Decisions)\s*\n([\s\S]*?)(?=\n#{1,4}\s|$)/i)
    return m ? truncate(m[1].trim(), 900) : ''
  }
  function sections(parts, max) { // Priorities are explicit; no silently dropped critical heading.
    let space = max
    const accepted = []
    for (const [name, value] of parts) {
      if (!value) continue
      const header = `\n## ${name}\n`
      const room = space - header.length - 24
      if (room <= 0) break
      const entry = header + truncate(value, room) + '\n'
      accepted.push(entry)
      space -= entry.length
    }
    return accepted.join('')
  }
  // Access control is enforced on every injection path, not just in the agent prompt.
  // The orchestrator can inspect global state. Child roles receive only their own
  // historical work; cross-role evidence must be included explicitly in the task.
  async function context(id, role) {
    if (!ROLES.has(role)) return '' // Unknown identity: fail closed.
    const primary = await rootId(id)
    const dir = await folder(primary)
    const handoffs = await listHandoffs(dir)
    let parts
    if (role === 'orchestrator') {
      const [session, decisions] = await Promise.all([
        read(join(dir, 'session.md'), 3500),
        read(join(dir, 'decisions.md'), 2400),
      ])
      const recent = handoffs.slice(-MAX_HANDOFFS)
      const reports = await Promise.all(recent.map(async f => `### ${f}\n${await read(join(dir, 'handoffs', f), 1700)}`))
      parts = [
        ['Текущее состояние', session || defaultSession],
        ['Решения (могут быть пересмотрены)', decisions || emptyDecisions],
        [`Последние ${MAX_HANDOFFS} передачи`, reports.join('\n\n')],
      ]
    } else {
      // Match the filename suffix, not a substring in the report body.
      const own = handoffs.filter(f => f.endsWith(`-${role}.md`)).slice(-MAX_HANDOFFS)
      const reports = await Promise.all(own.map(async f => {
        const stored = await read(join(dir, 'handoffs', f), MAX_RECORD_CHARS + 1800)
        const report = stored.split('## Отчёт агента (не верифицирован автоматически)\n')[1]?.split('\n## Файлы, замеченные в записи вызова')[0]?.trim() ?? ''
        return report ? `### ${f}\n${truncate(report, 1700)}` : ''
      }))
      parts = [[`Последние ${MAX_HANDOFFS} собственных handoff`, reports.filter(Boolean).join('\n\n')]]
      if (!reports.some(Boolean)) return ''
    }
    const body = sections(parts, MAX_CONTEXT_CHARS - 900)
    if (!body.trim()) return ''
    return `\n<session-memory-context>\n${body}\n</session-memory-context>\n`
  }
  async function messages(id) {
    const result = unwrap(await client.session.messages({ path: { id } }))
    return Array.isArray(result) ? result : (result?.items ?? [])
  }
  async function changedInSession(id) {
    const all = await messages(id)
    const found = new Set()
    for (const msg of all) for (const part of (msg.parts ?? [])) {
      if (part?.type !== 'tool' || !WRITES.has(part.tool)) continue
      const args = part.state?.input ?? {}
      const path = args.filePath ?? args.file_path ?? args.path
      if (typeof path === 'string' && path) found.add(basename(path))
    }
    return [...found].slice(0, MAX_FILES)
  }
  async function latestAssistant(id) {
    const all = await messages(id)
    return [...all].reverse().filter(m => m.info?.role === 'assistant').map(textOf).find(x => x.trim()) ?? ''
  }
  async function children(id) {
    try {
      const res = unwrap(await client.session.children({ path: { id } }))
      return Array.isArray(res) ? res : []
    } catch { return [] }
  }
  // Discover child/call correspondence even when idle arrives before task.after.
  async function lookupChild(parent, childID) {
    if (childCalls.has(childID)) return childCalls.get(childID)
    try {
      for (const message of await messages(parent)) for (const part of message.parts ?? []) {
        if (part.type !== 'tool' || !DELEGATE.has(part.tool)) continue
        const id = part.state?.metadata?.sessionId ?? part.state?.metadata?.sessionID ?? part.state?.metadata?.session_id
        if (id !== childID) continue
        const args = part.state?.input ?? {}
        return { callID: part.callID, agent: roleOf(args), task: scrub(args.prompt ?? '').replace(CONTEXT_PATTERN, '').trim() }
      }
    } catch (error) { await diagnostics(error) }
    return null
  }
  const normalize = (s) => scrub(s).replace(/\s+/g, ' ').trim()
  async function record(parent, agent, result, callID, childID, source = 'tool') {
    const rootSession = await rootId(parent)
    await serialize(rootSession, async () => {
      const dir = await ensure(rootSession)
      const key = childID ? `child:${childID}` : `call:${parent}:${callID || agent}`
      const registryFile = join(dir, 'registry.json')
      let registry = {}
      try { registry = JSON.parse(await readFile(registryFile, 'utf8')) } catch (e) { if (e?.code !== 'ENOENT') throw e }
      if (registry[key] || (callID && registry[`call:${parent}:${callID}`]) || seen.has(key)) return
      const files = await listHandoffs(dir)
      const number = String(Math.max(0, ...files.map(f => Number(f.match(/^\d+/)?.[0]) || 0)) + 1).padStart(5, '0')
      const state = calls.get(`${parent}:${callID}`) ?? (childID ? await lookupChild(parent, childID) : null)
      const task = state?.task ?? ''
      const changed = [...(state?.files ?? [])]
      if (childID) { try { changed.push(...await changedInSession(childID)) } catch {} }
      const changedUnique = [...new Set(changed.filter(Boolean))].slice(0, MAX_FILES)
      const summary = summarizeText(result)
      const now = new Date().toISOString()
      const filename = `${number}-${agent}.md`
      const handoff = `# Handoff ${number}: ${agent}\n\n- Время: ${now}\n- Агент: ${agent}\n- Родительская сессия: ${parent}\n- Дочерняя сессия: ${childID || 'не определена'}\n- Источник: ${source}\n- Статус: ${result.trim() ? 'получен ответ' : 'результат недоступен'}\n\n## Задание\n${truncate(task || 'Не восстановлено.', 500)}\n\n## Отчёт агента (не верифицирован автоматически)\n${summary}\n\n## Файлы, замеченные в записи вызова\n${changedUnique.length ? changedUnique.map(x => `- ${x}`).join('\n') : 'Не зафиксированы.'}\n`
      await atomic(join(dir, 'handoffs', filename), handoff)
      // Machine-readable source of truth; MD files are bounded human-readable projections.
      const stateFile = join(dir, 'state.json')
      let snapshot = { goal: '', history: [], decisions: [], files: [], tests: '' }
      try { snapshot = { ...snapshot, ...JSON.parse(await readFile(stateFile, 'utf8')) } } catch (e) { if (e?.code !== 'ENOENT') throw e }
      if (!snapshot.goal && task) snapshot.goal = truncate(task, 900)
      snapshot.history.push({ agent, file: filename, result: truncate(summary, 850), at: now })
      snapshot.history = snapshot.history.slice(-12)
      snapshot.files = [...new Set([...snapshot.files, ...changedUnique])].slice(-MAX_FILES)
      if (agent === 'tester') snapshot.tests = truncate(summary, 1100)
      const decision = extractDecisions(summary)
      if (decision && !snapshot.decisions.some(d => normalize(d.text) === normalize(decision))) {
        snapshot.decisions.push({ agent, text: decision, at: now })
        snapshot.decisions = snapshot.decisions.slice(-8)
      }
      await atomic(stateFile, JSON.stringify(snapshot, null, 2) + '\n')
      await atomic(join(dir, 'agents', `${agent}.md`), `# Последний известный результат ${agent}\n\nИсточник: ${filename}\n\n${summary}\n`)
      await atomic(join(dir, 'session.md'), `# Состояние сессии\n\n## Исходная цель\n${snapshot.goal || 'Не восстановлена.'}\n\n## Ход работы (от ранних к новым)\n${snapshot.history.slice(-6).map(x => `- ${x.agent} (${x.file}): ${truncate(x.result.replace(/\n/g, ' '), 320)}`).join('\n')}\n\n## Затронутые файлы\n${snapshot.files.length ? snapshot.files.map(f => `- ${f}`).join('\n') : 'Нет подтверждённых путей.'}\n\n## Последнее сообщение tester\n${snapshot.tests || 'Проверки не зафиксированы.'}\n\n## Следующий шаг (из последнего handoff)\n${truncate(summary.match(/(?:^|\n)#{1,4}\s*Следующий шаг\s*\n([\s\S]*?)(?=\n#{1,4}\s|$)/i)?.[1] ?? 'Смотреть последний handoff.', 600)}\n`)
      const decisionText = snapshot.decisions.length ? snapshot.decisions.map((d,i) => `## ${i+1}. ${d.at} — ${d.agent} (${i === snapshot.decisions.length - 1 ? 'последняя запись' : 'историческая запись; возможен пересмотр'})\n${d.text}`).join('\n\n') : 'Решения пока не зафиксированы.'
      await atomic(join(dir, 'decisions.md'), `# Решения\n\nЗаписи хронологические; при противоречии проверяй более позднее решение и исходные файлы.\n\n${decisionText}\n`)
      registry[key] = filename
      if (callID) registry[`call:${parent}:${callID}`] = filename
      await atomic(registryFile, JSON.stringify(registry, null, 2) + '\n')
      seen.add(key)
    })
  }
  return {
    'tool.execute.before': async (input, output) => {
      try {
        if (WRITES.has(input.tool)) {
          const found = calls.get(`${input.sessionID}:_active`)
          if (found) found.files.add(basename(output.args?.filePath ?? output.args?.path))
        }
        if (!DELEGATE.has(input.tool)) return
        const agent = roleOf(output.args)
        if (!agent || typeof output.args?.prompt !== 'string') return
        const key = `${input.sessionID}:${input.callID}`
        const cleanPrompt = output.args.prompt.replace(CONTEXT_PATTERN, '').replace(HANDOFF_INSTRUCTION, '').trimEnd()
        const state = calls.get(key) ?? { task: truncate(cleanPrompt, 1000), agent, files: new Set() }
        calls.set(key, state)
        calls.set(`${input.sessionID}:_active`, state)
        const memo = await context(input.sessionID, agent)
        // Mutation of an existing property is more portable than replacing output.args.
        output.args.prompt = `${cleanPrompt}${memo ? `\n\n${memo}` : ''}\n\n${HANDOFF_INSTRUCTION}`
      } catch (e) { await diagnostics(e) }
    },
    'tool.execute.after': async (input, output) => {
      if (!DELEGATE.has(input.tool)) return
      try {
        const state = calls.get(`${input.sessionID}:${input.callID}`)
        if (!state?.agent) return
        state.files = [...state.files].filter(Boolean)
        const child = output.metadata?.sessionId ?? output.metadata?.sessionID ?? output.metadata?.session_id ?? output.metadata?.session?.id ?? null
        const result = child ? await latestAssistant(child).catch(() => String(output.output ?? '')) : String(output.output ?? '')
        if (child) childCalls.set(child, { ...state, callID: input.callID })
        await record(input.sessionID, state.agent, result, input.callID, child)
        calls.delete(`${input.sessionID}:${input.callID}`)
        calls.delete(`${input.sessionID}:_active`)
      } catch (e) { await diagnostics(e) }
    },
    'experimental.chat.system.transform': async (input, output) => {
      try {
        if (!input?.sessionID || !Array.isArray(output?.system)) return
        const s = await info(input.sessionID)
        const agent = input.agent ?? s?.agent ?? roles.get(input.sessionID) ?? (s?.parentID ? null : 'orchestrator')
        if (ROLES.has(agent)) roles.set(input.sessionID, agent)
        const memo = await context(input.sessionID, agent)
        // Prompt-side injection is already present while a matching delegation runs.
        const active = s?.parentID && [...calls.entries()].some(([key, v]) => key.startsWith(`${s.parentID}:`) && !key.endsWith(':_active') && v.agent === agent)
        if (memo && !active && !output.system.some(line => line.includes('<session-memory-context>'))) output.system.push(memo)
      } catch (e) { await diagnostics(e) }
    },
    event: async ({ event }) => {
      if (event?.type !== 'session.idle') return
      const id = event.properties?.sessionID
      if (!id) return
      try {
        const s = await info(id)
        if (!s?.parentID) return
        // Fallback if the task tool post-execution hook was skipped.
        const parent = s.parentID
        const child = (await children(parent)).find(x => x?.id === id)
        if (!child) return
        const linked = await lookupChild(parent, id)
        if ([...calls.entries()].some(([key, v]) => key.startsWith(`${parent}:`) && !key.endsWith(':_active') && v.agent === (linked?.agent ?? roles.get(id)) && !linked?.callID)) return
        const result = await latestAssistant(id)
        if (result) {
          const lastMessages = await messages(id)
          const assistant = [...lastMessages].reverse().find(m => m.info?.role === 'assistant')
          const role = linked?.agent ?? roles.get(id) ?? assistant?.info?.agent ?? null
          if (ROLES.has(role)) await record(parent, role, result, linked?.callID, id, 'session.idle')
        }
      } catch (e) { await diagnostics(e) }
    },
  }
}
