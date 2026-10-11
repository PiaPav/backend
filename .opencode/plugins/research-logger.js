import { mkdir, readdir, rename, writeFile } from 'node:fs/promises'
import { join, resolve } from 'node:path'

// OpenCode v1 plugin. No external dependencies, no extra model calls.
const VERSION = 3
const MAX_PROMPT = 900
const MAX_REPLY = 1300
const MAX_TOOL_TEXT = 180
const MAX_TOOLS = 35
const MAX_ASSISTANT_STEPS = 24
const MAX_SUBAGENTS = 30
const MAX_SUBAGENT_RESULT = 500
const DELEGATE_TOOLS = new Set(['task', 'delegate_task', 'subagent'])
const SECRET = /(?:sk-[\w-]{12,}|gh[pousr]_[\w-]{12,}|github_pat_[\w-]{12,}|AKIA[0-9A-Z]{16}|Bearer\s+[\w.\-]{12,}|(?:api[_-]?key|access[_-]?token|secret|password|authorization)\s*[:=]\s*[^\s,;]+)/gi
const MASK_KEYS = /(?:token|password|secret|authorization|credential|api.?key|cookie|private.?key)/i
const WRITES = new Set(['write', 'edit', 'patch', 'apply_patch', 'multiedit'])

function redact(value) { return String(value ?? '').replace(SECRET, '[REDACTED]') }
function compact(value, limit = 200) {
  const s = redact(value).replace(/\s+/g, ' ').trim()
  return s.length > limit ? s.slice(0, limit - 1) + '…' : s
}
function slug(v) {
  return String(v ?? 'untitled').normalize('NFKD').toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '').slice(0, 52) || 'untitled'
}
function safeObject(obj, depth = 0) {
  if (depth > 2) return '[nested]'
  if (obj == null || typeof obj !== 'object') return typeof obj === 'string' ? compact(obj, 130) : obj
  if (Array.isArray(obj)) return obj.slice(0, 6).map(x => safeObject(x, depth + 1))
  const out = {}
  for (const [k, v] of Object.entries(obj).slice(0, 12)) {
    if (MASK_KEYS.test(k)) { out[k] = '[REDACTED]'; continue }
    if (/^(?:content|body|data|image|base64|messages|headers|env|environment)$/i.test(k)) continue
    out[k] = safeObject(v, depth + 1)
  }
  return out
}
function pickArgs(tool, args) {
  if (!args || typeof args !== 'object') return {}
  const names = ['filePath', 'file_path', 'path', 'pattern', 'query', 'description', 'url', 'command', 'prompt', 'subagent_type', 'agent', 'task_id', 'session_id', 'sessionID', 'offset', 'limit']
  const out = {}
  for (const k of names) if (args[k] != null) out[k] = compact(args[k], k === 'command' ? 180 : 130)
  if (!Object.keys(out).length) return safeObject(args)
  return out
}
function partText(parts, limit) {
  return compact((parts ?? []).filter(p => p?.type === 'text' && !p.synthetic).map(p => p.text).join('\n'), limit)
}
function idOf(x) { return x?.info?.id ?? x?.id }
function extractTool(p) {
  const state = p.state ?? {}
  const input = state.input ?? {}
  const out = { name: p.tool ?? 'tool', call: p.callID, status: state.status ?? 'unknown' }
  const args = pickArgs(out.name, input)
  if (Object.keys(args).length) out.args = args
  if (state.title) out.title = compact(state.title, 100)
  const file = input.filePath ?? input.file_path ?? input.path
  if (file && WRITES.has(out.name)) out.changed = compact(file, 180)
  if (state.status === 'error') out.error = compact(state.error ?? state.output, MAX_TOOL_TEXT)
  else if (state.status === 'completed' && state.output && !WRITES.has(out.name)) out.result = compact(state.output, MAX_TOOL_TEXT)
  if (state.time?.start && state.time?.end) out.ms = state.time.end - state.time.start
  return out
}
// Tool results may contain OpenCode task-control tags. Keep only human-readable content.
function cleanTaskResult(value) {
  let s = String(value ?? '')
  s = s.replace(/<task\b[^>]*>/gi, '').replace(/<\/task\s*>/gi, '')
  s = s.replace(/<task_metadata>[\s\S]*?<\/task_metadata>/gi, '')
  s = s.replace(/^(?:Task ID|Session ID|Status|Duration|Agent):[^\n]*\n/gim, '')
  return compact(s, MAX_SUBAGENT_RESULT)
}
function dateLabel(ts) { return new Date(ts).toISOString().slice(0, 10) }
function pad(num) { return String(num).padStart(3, '0') }
function unwrap(v) { return v?.data ?? v }
async function atomicJSON(path, obj) {
  const temp = `${path}.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`
  await writeFile(temp, JSON.stringify(obj, null, 2) + '\n', { mode: 0o600 })
  await rename(temp, path)
}

export const ResearchLogger = async ({ directory, client }) => {
  const root = resolve(directory, 'research', 'logs')
  const locations = new Map()
  const busy = new Map()
  const knownParents = new Map()

  const enqueue = (id, job) => {
    const prev = busy.get(id) ?? Promise.resolve()
    const next = prev.catch(() => {}).then(job)
    busy.set(id, next)
    void next.finally(() => { if (busy.get(id) === next) busy.delete(id) }).catch(() => {})
    return next
  }

  async function location(session) {
    const id = session.id
    if (locations.has(id)) return locations.get(id)
    const created = session.time?.created ?? Date.now()
    const day = dateLabel(created)
    const base = join(root, day)
    await mkdir(base, { recursive: true })
    const entries = await readdir(base, { withFileTypes: true })
    // The stable 12-char ID suffix lets restarts reuse the same directory.
    const suffix = id.slice(-12).replace(/[^a-zA-Z0-9_-]/g, '')
    const existing = entries.find(e => e.isDirectory() && e.name.endsWith(`--${suffix}`))
    if (existing) {
      const dir = join(base, existing.name)
      locations.set(id, dir)
      return dir
    }
    const used = new Set(entries.filter(e => e.isDirectory()).map(e => Number(e.name.match(/^s(\d+)-/)?.[1])))
    let n = 1, dir
    for (;;) {
      while (used.has(n)) n++
      dir = join(base, `s${pad(n)}-${slug(redact(session.title))}--${suffix}`)
      try { await mkdir(dir); break }
      catch (e) { if (e?.code !== 'EEXIST') throw e; n++ }
    }
    locations.set(id, dir)
    return dir
  }

  async function getMessages(sessionID) {
    const result = unwrap(await client.session.messages({ path: { id: sessionID } }))
    return Array.isArray(result) ? result : (result?.items ?? [])
  }

  async function save(sessionID) {
    const session = unwrap(await client.session.get({ path: { id: sessionID } }))
    if (!session?.id) return
    const folder = await location(session)
    if (session.parentID) knownParents.set(sessionID, session.parentID)
    const messages = await getMessages(sessionID)
    const turns = []
    let turn
    for (const item of messages) {
      const info = item.info ?? {}
      if (info.role === 'user') {
        if (turn) turns.push(turn)
        turn = { user: item, assistants: [] }
      } else if (info.role === 'assistant' && turn) {
        turn.assistants.push(item)
      }
    }
    if (turn) turns.push(turn)
    const written = []
    const allModels = new Set()
    let sumTools = 0
    const childRefs = []

    // Child sessions have parentID and will be saved in their own numbered folder.
    try {
      const children = unwrap(await client.session.children({ path: { id: sessionID } }))
      for (const child of (Array.isArray(children) ? children : []).slice(0, MAX_SUBAGENTS)) {
        if (child?.id) {
          const childFolder = await location(child)
          childRefs.push({ session: child.id, title: compact(child.title, 100), log: childFolder.slice(root.length + 1).replaceAll('\\', '/') + '/index.json' })
        }
      }
    } catch { /* Child listing is optional across SDK versions. */ }

    for (let index = 0; index < turns.length; index++) {
      const item = turns[index]
      // Do not write a successful "answer" record before a reply exists.
      if (!item.assistants.length) continue
      const start = item.user.info ?? {}
      const steps = item.assistants.map(a => {
        const i = a.info ?? {}
        const model = [i.providerID ?? i.model?.providerID, i.modelID ?? i.model?.modelID].filter(Boolean).join('/')
        if (model) allModels.add(model)
        const tools = (a.parts ?? []).filter(p => p?.type === 'tool').map(extractTool)
        sumTools += tools.length
        const t = i.tokens
        return {
          agent: i.agent ?? i.mode,
          ...(model ? { model } : {}),
          ...(typeof i.temperature === 'number' ? { temperature: i.temperature } : {}),
          ...(typeof i.topP === 'number' ? { top_p: i.topP } : {}),
          ...(typeof i.seed === 'number' ? { seed: i.seed } : {}),
          ...(t ? { tokens: { in: t.input, out: t.output, reasoning: t.reasoning } } : {}),
          ...(partText(a.parts, MAX_REPLY) ? { text: partText(a.parts, MAX_REPLY) } : {}),
          tools
        }
      })
      const allTools = steps.flatMap(s => s.tools)
      const delegations = allTools.filter(t => DELEGATE_TOOLS.has(t.name) || t.args?.subagent_type)
      // Delegation appears ONLY in subagent_calls; ordinary tools stay in tools.
      const tools = allTools.filter(t => !delegations.includes(t))
      const latest = [...steps].reverse().find(s => s.text)
      const files = [...new Set(allTools.map(t => t.changed).filter(Boolean))].slice(0, 30)
      const subagents = delegations.slice(0, MAX_SUBAGENTS).map(t => {
        const entry = {
          call: t.call,
          agent: t.args?.subagent_type ?? t.args?.agent,
          task: t.args?.description ?? t.args?.prompt,
          status: t.status
        }
        const id = t.args?.session_id ?? t.args?.sessionID
        if (id) entry.session = id
        return { entry, fallback: t.result ?? t.error }
      })
      // Link only when unambiguous. Avoid claiming an uncertain call/session match.
      if (subagents.length === 1 && childRefs.length === 1 && !subagents[0].entry.session) {
        subagents[0].entry.session = childRefs[0].session
      }
      for (const item of subagents) {
        const entry = item.entry
        const match = childRefs.find(c => c.session === entry.session)
        if (match) {
          entry.log = match.log
          // Prefer the actual child answer over the tool's XML/control envelope.
          try {
            const childMessages = await getMessages(match.session)
            const lastAnswer = [...childMessages].reverse()
              .filter(m => m.info?.role === 'assistant')
              .map(m => partText(m.parts, MAX_SUBAGENT_RESULT))
              .find(Boolean)
            if (lastAnswer) entry.result = lastAnswer
          } catch { /* Fall back to cleaned tool output. */ }
        }
        if (!entry.result && item.fallback) entry.result = cleanTaskResult(item.fallback)
      }
      const record = {
        schema: VERSION,
        session: sessionID,
        turn: index + 1,
        at: new Date(start.time?.created ?? Date.now()).toISOString(),
        user: { text: partText(item.user.parts, MAX_PROMPT) },
        assistant: { answer: latest?.text ?? '', agents: [...new Set(steps.map(s => s.agent).filter(Boolean))], models: [...new Set(steps.map(s => s.model).filter(Boolean))] },
        ...(steps.length ? { generation: steps.slice(0, MAX_ASSISTANT_STEPS).map(({ agent, model, temperature, top_p, seed, tokens }) => ({ agent, model, temperature, top_p, seed, tokens })) } : {}),
        ...(tools.length ? { tools: tools.slice(0, MAX_TOOLS), tools_total: tools.length } : {}),
        ...(files.length ? { changed_files: files } : {}),
        ...(subagents.length ? { subagent_calls: subagents.map(s => s.entry) } : {}),
        ...(steps.length > MAX_ASSISTANT_STEPS || tools.length > MAX_TOOLS ? { truncated: true } : {})
      }
      const file = `turn-${pad(index + 1)}.json`
      await atomicJSON(join(folder, file), record)
      written.push(file)
    }
    const manifest = {
      schema: VERSION,
      session: sessionID,
      title: compact(session.title, 160),
      parent_session: session.parentID || null,
      project: directory,
      created: new Date(session.time?.created ?? Date.now()).toISOString(),
      updated: new Date().toISOString(),
      turns: written.length,
      tools: sumTools,
      models: [...allModels],
      child_sessions: childRefs,
      role: session.parentID ? 'subagent' : 'primary',
      files: written
    }
    await atomicJSON(join(folder, 'index.json'), manifest)
  }

  async function scheduleSave(id) {
    if (!id) return
    await enqueue(id, async () => {
      try { await save(id) }
      catch (error) {
        // Logging must never break an OpenCode task.
        await client.app.log({ body: { service: 'research-logger', level: 'warn', message: String(error) } }).catch(() => {})
      }
    })
  }

  return {
    'tool.execute.after': async (input) => {
      // Delegation has returned: persist the parent even before session.idle.
      if (DELEGATE_TOOLS.has(input.tool)) await scheduleSave(input.sessionID)
    },
    event: async ({ event }) => {
      if (event.type === 'session.idle') {
        const id = event.properties?.sessionID
        await scheduleSave(id)
        // A child's idle event may arrive while the parent is still running.
        // Reconcile the parent so its folder and child references are not missing.
        let parent = knownParents.get(id)
        if (!parent && id) {
          try {
            const info = unwrap(await client.session.get({ path: { id } }))
            parent = info?.parentID
          } catch {}
        }
        if (parent) await scheduleSave(parent)
      }
      // Child sessions are also saved when they become idle.
      if (event.type === 'session.deleted') locations.delete(event.properties?.info?.id ?? event.properties?.sessionID)
    }
  }
}
