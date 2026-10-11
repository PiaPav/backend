#!/usr/bin/env python3
"""Research Logger v3 viewer. Python 3.9+, standard library only (Tkinter)."""
import json
import os
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path, PureWindowsPath
from tkinter import filedialog, messagebox, ttk

MAX_FILE_BYTES = 2_000_000


def read_json(path):
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('Файл слишком большой для просмотра (>2 МБ)')
    with path.open('r', encoding='utf-8-sig') as f:
        return json.load(f)


def text(value):
    if value is None:
        return ''
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def stamp(value):
    if not value:
        return ''
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, TypeError):
        return str(value)


def short(value, width=80):
    s = ' '.join(text(value).split())
    return s if len(s) <= width else s[:width-1] + '…'


class Viewer(tk.Tk):
    def __init__(self, source=None):
        super().__init__()
        self.title('OpenCode · Research Logs Viewer')
        self.geometry('1250x790')
        self.minsize(850, 550)
        self.root_dir = None
        self.nodes = {}
        self.session_paths = {}
        self.search = tk.StringVar()
        self.status = tk.StringVar(value='Выберите папку research/logs')
        self._build()
        if source:
            self.open_dir(source)
        else:
            for candidate in (Path.cwd() / 'research' / 'logs', Path.cwd()):
                if candidate.name == 'logs' and candidate.is_dir():
                    self.open_dir(candidate)
                    break

    def _build(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill='x')
        ttk.Button(top, text='Открыть папку', command=self.choose_dir).pack(side='left')
        ttk.Button(top, text='Обновить', command=self.refresh).pack(side='left', padx=(6, 12))
        ttk.Label(top, text='Поиск по папкам / названиям:').pack(side='left')
        entry = ttk.Entry(top, textvariable=self.search, width=30)
        entry.pack(side='left', padx=7)
        self.search.trace_add('write', lambda *_: self.populate())
        ttk.Button(top, text='Сбросить', command=lambda: self.search.set('')).pack(side='left')
        pane = ttk.Panedwindow(self, orient='horizontal')
        pane.pack(fill='both', expand=True, padx=8, pady=(0, 5))
        left = ttk.Frame(pane)
        pane.add(left, weight=1)
        self.tree = ttk.Treeview(left, columns=('kind',), show='tree', selectmode='browse')
        self.tree.pack(side='left', fill='both', expand=True)
        left_scroll = ttk.Scrollbar(left, orient='vertical', command=self.tree.yview)
        left_scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=left_scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.on_select)
        right = ttk.Frame(pane)
        pane.add(right, weight=3)
        self.heading = ttk.Label(right, text='Выберите сессию или ход', font=('TkDefaultFont', 13, 'bold'))
        self.heading.pack(anchor='w', pady=(0, 8))
        notebook = ttk.Notebook(right)
        notebook.pack(fill='both', expand=True)
        self.overview = self._text_tab(notebook, 'Обзор')
        self.timeline = self._text_tab(notebook, 'Хронология')
        self.raw = self._text_tab(notebook, 'JSON')
        ttk.Label(self, textvariable=self.status, anchor='w', padding=(8, 4)).pack(fill='x')

    def _text_tab(self, notebook, name):
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=name)
        widget = tk.Text(frame, wrap='word', state='disabled', font=('TkFixedFont', 10), padx=10, pady=10)
        scroll = ttk.Scrollbar(frame, command=widget.yview)
        scroll.pack(side='right', fill='y')
        widget.pack(side='left', fill='both', expand=True)
        widget.configure(yscrollcommand=scroll.set)
        widget.tag_configure('h', font=('TkDefaultFont', 11, 'bold'), spacing1=8, spacing3=4)
        widget.tag_configure('muted', foreground='#777777')
        return widget

    def put(self, widget, segments):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        for segment in segments:
            if isinstance(segment, tuple):
                widget.insert('end', segment[0], segment[1])
            else:
                widget.insert('end', segment)
        widget.configure(state='disabled')
        widget.yview_moveto(0)

    def choose_dir(self):
        folder = filedialog.askdirectory(title='Выберите research/logs или корень проекта')
        if folder:
            self.open_dir(Path(folder))

    def open_dir(self, directory):
        directory = Path(directory).expanduser().resolve()
        if (directory / 'research' / 'logs').is_dir():
            directory = directory / 'research' / 'logs'
        if not directory.is_dir():
            messagebox.showerror('Ошибка', f'Папка не найдена:\n{directory}')
            return
        self.root_dir = directory
        self.search.set('')
        self.populate()

    def refresh(self):
        self.populate()

    def populate(self):
        self.tree.delete(*self.tree.get_children())
        self.nodes.clear()
        self.session_paths.clear()
        if not self.root_dir:
            return
        term = self.search.get().casefold().strip()
        count = 0
        try:
            daydirs = sorted((p for p in self.root_dir.iterdir() if p.is_dir()), reverse=True)
            for day in daydirs:
                sessions = []
                for folder in sorted((p for p in day.iterdir() if p.is_dir()), key=lambda p: p.name):
                    manifest_file = folder / 'index.json'
                    if not manifest_file.is_file():
                        continue
                    try:
                        manifest = read_json(manifest_file)
                    except (OSError, ValueError, json.JSONDecodeError):
                        continue
                    title = str(manifest.get('title') or folder.name)
                    if term and term not in (day.name + ' ' + folder.name + ' ' + title + ' ' + str(manifest.get('session', ''))).casefold():
                        continue
                    sessions.append((folder, manifest))
                if not sessions:
                    continue
                day_id = self.tree.insert('', 'end', text=f'📅 {day.name}', open=True)
                self.nodes[day_id] = ('day', day, None)
                for folder, manifest in sessions:
                    role = '↳' if manifest.get('parent_session') else '●'
                    desc = f'{role} {folder.name.split("--")[0]}  ·  {short(manifest.get("title"), 45)}'
                    s_id = self.tree.insert(day_id, 'end', text=desc, open=False)
                    self.nodes[s_id] = ('session', folder, manifest)
                    if manifest.get('session'):
                        self.session_paths[manifest['session']] = folder
                    count += 1
                    turn_files = sorted(folder.glob('turn-*.json'))
                    for turn in turn_files:
                        t_id = self.tree.insert(s_id, 'end', text=f'    {turn.stem}')
                        self.nodes[t_id] = ('turn', turn, None)
        except OSError as exc:
            messagebox.showerror('Ошибка чтения', str(exc))
        self.status.set(f'{self.root_dir}    ·    сессий: {count}')
        self.heading.configure(text='Выберите сессию или ход')
        for widget in (self.overview, self.timeline, self.raw):
            self.put(widget, [])

    def on_select(self, _event=None):
        items = self.tree.selection()
        if not items:
            return
        kind, path, manifest = self.nodes.get(items[0], (None, None, None))
        if kind == 'day':
            self.heading.configure(text=path.name)
            return
        try:
            if kind == 'session':
                self.show_session(path, manifest)
            elif kind == 'turn':
                self.show_turn(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            messagebox.showerror('Ошибка чтения JSON', f'{path}\n\n{exc}')

    def show_session(self, folder, manifest):
        self.heading.configure(text=manifest.get('title') or folder.name)
        items = [
            ('СЕССИЯ\n', 'h'), f'Каталог: {folder.name}\n',
            f'ID: {manifest.get("session", "—")}\n',
            f'Роль: {manifest.get("role", "—")}\n',
            f'Создана: {stamp(manifest.get("created"))}\n',
            f'Обновлена: {stamp(manifest.get("updated"))}\n',
            f'Ходов: {manifest.get("turns", 0)} · вызовов инструментов (включая task): {manifest.get("tools", 0)}\n',
            f'Модели: {", ".join(manifest.get("models") or []) or "—"}\n',
            ('\nСВЯЗИ\n', 'h'),
            f'Родитель: {manifest.get("parent_session") or "—"}\n',
        ]
        for child in manifest.get('child_sessions') or []:
            items.append(f'Дочерняя сессия: {child.get("title") or "—"}\n  ID: {child.get("session", "—")}\n  Лог: {child.get("log", "—")}\n')
        if not manifest.get('child_sessions'):
            items.append('Дочерних сессий нет\n')
        self.put(self.overview, items)
        turns = []
        for filepath in sorted(folder.glob('turn-*.json')):
            try:
                turns.append((filepath, read_json(filepath)))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                turns.append((filepath, {'_error': str(exc)}))
        self.put(self.timeline, self.make_timeline(turns))
        self.put(self.raw, [json.dumps(manifest, ensure_ascii=False, indent=2)])

    def show_turn(self, filepath):
        record = read_json(filepath)
        self.heading.configure(text=f'{filepath.parent.name} / {filepath.name}')
        tools = record.get('tools') or []
        agents = record.get('subagent_calls') or []
        models = (record.get('assistant') or {}).get('models') or []
        tokens = [x.get('tokens') for x in record.get('generation', []) if isinstance(x, dict) and x.get('tokens')]
        summary = [
            ('ХОД\n', 'h'),
            f'Дата: {stamp(record.get("at"))}\n',
            f'Номер: {record.get("turn", "—")}\n',
            f'Модели: {", ".join(models) or "—"}\n',
            f'Инструментов: {len(tools)} · вызовов субагентов: {len(agents)}\n',
            f'Токены по шагам: {text(tokens) if tokens else "—"}\n',
        ]
        self.put(self.overview, summary)
        self.put(self.timeline, self.make_timeline([(filepath, record)]))
        self.put(self.raw, [json.dumps(record, ensure_ascii=False, indent=2)])

    def readable_path(self, value, project=None):
        """Use project-relative paths for Windows and POSIX logs."""
        if not value:
            return '—'
        original = str(value)
        if project:
            source = original.replace('\\', '/')
            prefix = str(project).replace('\\', '/').rstrip('/') + '/'
            if source.casefold().startswith(prefix.casefold()):
                return source[len(prefix):]
        return original

    def describe_tool(self, tool, project=None, indent=''):
        name = tool.get('name') or 'tool'
        args = tool.get('args') or {}
        paths = []
        for key in ('filePath', 'path', 'file_path', 'target', 'filename'):
            if isinstance(args.get(key), str):
                paths.append(self.readable_path(args[key], project))
        if name in ('bash', 'shell') and args.get('command'):
            label = str(args['command'])[:220]
        else:
            label = ', '.join(paths) if paths else (tool.get('title') or '')
        status = tool.get('status') or 'unknown'
        ms = tool.get('ms')
        timing = f' · {ms} мс' if ms is not None else ''
        output = [f'{indent}{name} · {status}{timing}\n']
        if label:
            output.append(f'{indent}Файл / цель: {label}\n')
        if not paths and not (name in ('bash', 'shell') and args.get('command')) and args:
            output.append(f'{indent}Аргументы: {text(args)}\n')
        if name in ('bash', 'shell') and args.get('command'):
            output.append(f'{indent}Команда: {label}\n')
        if tool.get('error'):
            output.append(f'{indent}Ошибка: {short(tool["error"], 350)}\n')
        # Results may be intentionally truncated by the logger.
        return output

    def find_child_for_call(self, parent_folder, turn, call):
        """Resolve a child's log by ID, or by creation time within the parent turn.

        Never claim a specific match when several child sessions are possible.
        """
        if not self.root_dir:
            return None
        index_file = parent_folder / 'index.json'
        if not index_file.is_file():
            return None
        try:
            manifest = read_json(index_file)
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        children = manifest.get('child_sessions') or []
        child_id = call.get('session')
        if child_id:
            candidates = [x for x in children if x.get('session') == child_id]
        elif call.get('log'):
            candidates = [x for x in children if x.get('log') == call['log']]
        else:
            # Match by turn time and agent, rather than by the globally first child.
            try:
                from datetime import timezone
                start = datetime.fromisoformat(turn['at'].replace('Z', '+00:00'))
                next_start = None
                for turn_file in sorted(parent_folder.glob('turn-*.json')):
                    candidate_turn = read_json(turn_file)
                    when = datetime.fromisoformat(candidate_turn['at'].replace('Z', '+00:00'))
                    if when > start and (next_start is None or when < next_start):
                        next_start = when
                candidates = []
                for child in children:
                    relpath = child.get('log')
                    if not relpath:
                        continue
                    f = self.root_dir / relpath
                    if not f.is_file():
                        continue
                    m = read_json(f)
                    born = datetime.fromisoformat(m['created'].replace('Z', '+00:00'))
                    if born < start or (next_start is not None and born >= next_start):
                        continue
                    agent = str(call.get('agent') or '').casefold()
                    if agent and ('@' + agent).casefold() not in str(m.get('title', '')).casefold():
                        continue
                    candidates.append(child)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                return None
        if len(candidates) != 1:
            return None
        child = candidates[0]
        relpath = child.get('log')
        if not relpath:
            return None
        index_path = self.root_dir / relpath
        try:
            index_path.resolve().relative_to(self.root_dir.resolve())
            manifest = read_json(index_path)
            child_turns = [read_json(f) for f in sorted(index_path.parent.glob('turn-*.json'))]
            return (manifest, child_turns, relpath)
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def make_timeline(self, turns):
        out = []
        for path, turn in turns:
            if '_error' in turn:
                out.extend([('ОШИБКА\n', 'h'), f'{path.name}: {turn["_error"]}\n'])
                continue
            out.extend([('─' * 45 + '\n'), (f'ХОД {turn.get("turn", path.stem)} · {stamp(turn.get("at"))}\n', 'h')])
            out.extend([('ПОЛЬЗОВАТЕЛЬ\n', 'h'), text((turn.get('user') or {}).get('text')) + '\n'])
            project = None
            try:
                project = read_json(path.parent / 'index.json').get('project')
            except (OSError, ValueError, json.JSONDecodeError):
                pass
            for idx, call in enumerate(turn.get('subagent_calls') or [], 1):
                child = self.find_child_for_call(path.parent, turn, call)
                child_turns = child[1] if child else []
                prompt = ((child_turns[0].get('user') or {}).get('text') if child_turns else None) or call.get('task') or '—'
                out.extend([('\nСУБАГЕНТ ' + str(idx) + '\n', 'h'),
                            f'Агент: {call.get("agent") or "—"}\n',
                            f'Исходный запрос: {prompt}\n',
                            f'Статус: {call.get("status") or "—"}\n'])
                if child:
                    out.append(f'Сессия: {child[0].get("session", "—")}\n')
                    out.append(f'Лог: {child[2]}\n')
                    for child_turn in child_turns:
                        for n, tool in enumerate(child_turn.get('tools') or [], 1):
                            out.append((f'\n  ИНСТРУМЕНТ СУБАГЕНТА {n}\n', 'h'))
                            out.extend(self.describe_tool(tool, child[0].get('project') or project, indent='  '))
                    reply = next((t.get('assistant', {}).get('answer') for t in reversed(child_turns) if t.get('assistant', {}).get('answer')), None)
                    out.append(f'\nОтвет субагента: {reply or call.get("result") or "—"}\n')
                else:
                    out.append('Дочерний журнал не удалось однозначно сопоставить.\n')
                    out.append(f'Ответ: {call.get("result") or "—"}\n')
            for idx, tool in enumerate(turn.get('tools') or [], 1):
                out.append((f'\nИНСТРУМЕНТ ОРКЕСТРАТОРА {idx}\n', 'h'))
                out.extend(self.describe_tool(tool, project))
            if turn.get('changed_files'):
                out.extend([('\nИЗМЕНЁННЫЕ ФАЙЛЫ\n', 'h'), '\n'.join(map(str, turn['changed_files'])) + '\n'])
            out.extend([('\nОТВЕТ АССИСТЕНТА\n', 'h'),
                        text((turn.get('assistant') or {}).get('answer')) + '\n\n'])
        return out or ['Записей нет']


if __name__ == '__main__':
    arg = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    Viewer(arg).mainloop()
