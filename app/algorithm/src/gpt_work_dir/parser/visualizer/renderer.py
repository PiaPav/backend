"""Create a standalone grouped visualization of a parser graph.

Usage::

    visualize_graph(starter(project), "graph.html")
    python -m gpt_work_dir.parser.visualizer graph.json -o graph.html --open
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from collections.abc import Mapping
from pathlib import Path
from typing import Any

GraphInput = Mapping[str, Any] | str | Path


def _read_graph(value: GraphInput) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, Path):
        return json.loads(value.read_text(encoding="utf-8"))
    if value == "-":
        import sys

        return json.load(sys.stdin)
    candidate = Path(value)
    try:
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    except OSError:
        pass
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            "graph must be a dictionary, a JSON string, or a path to a JSON file"
        ) from exc
    if not isinstance(loaded, dict):
        raise ValueError("the graph JSON root must be an object")
    return loaded


def graph_to_html(graph: Mapping[str, Any]) -> str:
    """Return a self-contained page with nodes grouped by source file."""
    payload = json.dumps(graph, ensure_ascii=False, separators=(",", ":"))
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return _HTML_TEMPLATE.replace("__GRAPH_DATA__", payload)


def visualize_graph(
    graph: GraphInput,
    output_path: str | Path = "graph.html",
    *,
    open_browser: bool = False,
) -> Path:
    """Write the visualization and optionally open it in the default browser."""
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(graph_to_html(_read_graph(graph)), encoding="utf-8")
    if open_browser:
        webbrowser.open(destination.as_uri())
    return destination


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Visualize the JSON graph produced by parser.starter()."
    )
    parser.add_argument("graph", help="JSON file, JSON string, or '-' for stdin")
    parser.add_argument("-o", "--output", default="graph.html", help="output HTML file")
    parser.add_argument(
        "--open", action="store_true", dest="open_browser", help="open the result"
    )
    args = parser.parse_args()
    result = visualize_graph(args.graph, args.output, open_browser=args.open_browser)
    print(result)
    return 0


_HTML_TEMPLATE = r'''<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Структура Python-проекта</title>
  <style>
    :root {
      color-scheme: light dark;
      --bg:#f6f7fa; --surface:#fff; --surface-soft:#f0f3f8; --text:#18202b;
      --muted:#687386; --border:#cfd6e2; --line:#8d98aa; --selected:#2563eb;
      --class:#7c3aed; --function:#0891b2; --method:#0f766e;
      --constant:#ca8a04; --module:#dc2626; --shadow:rgba(15,23,42,.16);
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --bg:#10141c; --surface:#1a202b; --surface-soft:#222a37; --text:#edf2f7;
        --muted:#a8b2c2; --border:#3c485a; --line:#69768a; --selected:#60a5fa;
        --class:#a78bfa; --function:#22d3ee; --method:#5eead4;
        --constant:#facc15; --module:#fb7185; --shadow:rgba(0,0,0,.4);
      }
    }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font:14px/1.45 system-ui,sans-serif; }
    header { display:flex; align-items:center; gap:16px; padding:13px 18px; background:var(--surface); border-bottom:1px solid var(--border); }
    h1 { margin:0; font-size:18px; font-weight:600; }
    .summary { margin-right:auto; color:var(--muted); }
    button { padding:6px 10px; border:1px solid var(--border); border-radius:7px; background:var(--surface); color:var(--text); font:inherit; cursor:pointer; }
    button:hover { border-color:var(--selected); }
    main { position:relative; height:calc(100vh - 57px); min-height:500px; overflow:hidden; }
    svg { width:100%; height:100%; display:block; touch-action:none; cursor:grab; }
    svg.panning { cursor:grabbing; }
    .relation { stroke:var(--line); stroke-width:1.3; opacity:.72; marker-end:url(#arrow); }
    .relation-label { fill:var(--muted); font-size:10px; text-anchor:middle; pointer-events:none; paint-order:stroke; stroke:var(--bg); stroke-width:3px; }
    .directory-group { cursor:move; }
    .directory-group.dragging { cursor:grabbing; }
    .directory-frame { fill:color-mix(in srgb,var(--surface) 64%,transparent); stroke:var(--border); stroke-width:1.5; stroke-dasharray:7 5; }
    .directory-group[data-depth="0"] > .directory-frame { fill:color-mix(in srgb,var(--surface-soft) 45%,transparent); stroke-width:2; stroke-dasharray:none; }
    .directory-title-bg { fill:var(--surface-soft); stroke:var(--border); stroke-width:1; }
    .directory-title { fill:var(--text); font-size:13px; font-weight:600; pointer-events:none; }
    .directory-path { fill:var(--muted); font-size:10px; pointer-events:none; }
    .file-group { cursor:move; }
    .file-frame { fill:var(--surface); stroke:var(--border); stroke-width:1.5; filter:drop-shadow(0 4px 5px var(--shadow)); }
    .file-group.selected .file-frame { stroke:var(--selected); stroke-width:3; }
    .file-header { fill:var(--surface-soft); }
    .file-title { fill:var(--text); font-size:14px; font-weight:600; pointer-events:none; }
    .file-count { fill:var(--muted); font-size:11px; text-anchor:end; pointer-events:none; }
    .node { cursor:pointer; }
    .node-shape { fill:var(--surface-soft); stroke-width:2; }
    .node[data-kind="class"] .node-shape { stroke:var(--class); }
    .node[data-kind="function"] .node-shape { stroke:var(--function); }
    .node[data-kind="method"] .node-shape { stroke:var(--method); }
    .node[data-kind="constant"] .node-shape { stroke:var(--constant); }
    .node[data-kind="module"] .node-shape { stroke:var(--module); }
    .node.selected .node-shape { stroke:var(--selected); stroke-width:4; }
    .node-label { fill:var(--text); font-size:11px; text-anchor:middle; pointer-events:none; }
    .node-kind { fill:var(--muted); font-size:9px; text-anchor:middle; pointer-events:none; }
    .details { position:absolute; z-index:10; width:min(410px,calc(100% - 24px)); max-height:min(540px,calc(100% - 24px)); overflow:auto; padding:14px; background:var(--surface); border:1px solid var(--border); border-radius:10px; box-shadow:0 14px 35px var(--shadow); }
    .details[hidden] { display:none; }
    .render-error { position:absolute; top:16px; left:50%; transform:translateX(-50%); width:min(620px,calc(100% - 32px)); padding:12px 14px; background:var(--surface); border:1px solid var(--module); border-radius:8px; color:var(--text); box-shadow:0 8px 24px var(--shadow); }
    .details-head { display:flex; align-items:start; gap:10px; }
    .details h2 { margin:0; font-size:16px; overflow-wrap:anywhere; }
    .details .kind { margin:2px 0 10px; color:var(--muted); }
    .details .close { margin-left:auto; border:0; padding:1px 7px; font-size:19px; }
    details { padding-top:9px; border-top:1px solid var(--border); }
    summary { cursor:pointer; font-weight:600; }
    pre { margin:9px 0 0; white-space:pre-wrap; overflow-wrap:anywhere; color:var(--text); font:12px/1.5 ui-monospace,monospace; }
    .legend { position:absolute; left:12px; bottom:12px; display:flex; flex-wrap:wrap; gap:8px 13px; max-width:calc(100% - 24px); padding:7px 10px; background:var(--surface); border:1px solid var(--border); border-radius:8px; color:var(--muted); font-size:12px; pointer-events:none; }
    .legend span::before { content:""; display:inline-block; width:9px; height:9px; margin-right:5px; border:2px solid var(--dot); border-radius:3px; vertical-align:-1px; }
    @media (max-width:600px) {
      .summary { display:none; }
      .details { left:12px !important; right:12px; bottom:52px; top:auto !important; width:auto; max-height:48%; }
    }
  </style>
</head>
<body>
  <header><h1>Структура Python-проекта</h1><div class="summary" id="summary"></div><button type="button" id="reset">Показать целиком</button></header>
  <main id="stage">
    <svg id="graph" role="img" aria-label="Элементы проекта, сгруппированные по каталогам и Python-файлам">
      <defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="var(--line)"></path></marker></defs>
      <g id="viewport"><g id="directories"></g><g id="files"></g><g id="relations"></g><g id="nodes"></g></g>
    </svg>
    <aside class="details" id="details" hidden aria-live="polite">
      <div class="details-head"><div><h2 id="detail-title"></h2><div class="kind" id="detail-kind"></div></div><button type="button" class="close" id="close" aria-label="Закрыть">×</button></div>
      <details open><summary>Подробности</summary><pre id="detail-json"></pre></details>
    </aside>
    <div class="legend" aria-label="Обозначения">
      <span style="--dot:var(--class)">класс</span><span style="--dot:var(--function)">функция</span>
      <span style="--dot:var(--method)">метод</span><span style="--dot:var(--constant)">константа</span>
      <span style="--dot:var(--module)">код модуля</span>
    </div>
  </main>
  <script id="graph-data" type="application/json">__GRAPH_DATA__</script>
  <script>
  (() => {
    try {
    const source = JSON.parse(document.getElementById('graph-data').textContent);
    const svg = document.getElementById('graph');
    const viewport = document.getElementById('viewport');
    const relationsLayer = document.getElementById('relations');
    const directoriesLayer = document.getElementById('directories');
    const filesLayer = document.getElementById('files');
    const nodesLayer = document.getElementById('nodes');
    const details = document.getElementById('details');
    const ns = 'http://www.w3.org/2000/svg';
    const files = [], folders = [], nodes = [], relations = [], symbols = new Map(), moduleNodes = new Map();
    const fileWidth = 330, headerHeight = 48, cellWidth = 294, cellHeight = 58;
    let sequence = 0, selected = null, transform = {x:0,y:0,k:1}, pan = null;

    const rootFolder = {id:'d0',name:'Корень проекта',path:[],parent:null,children:[],files:[],depth:0,x:0,y:0,width:0,height:0,element:null};
    const folderByPath = new Map([['',rootFolder]]); folders.push(rootFolder);
    const pathPartsOf = data => Array.isArray(data.path_parts)
      ? data.path_parts.map(String).filter(Boolean)
      : String(data.path || '').split('.').filter(Boolean);
    const ensureFolder = parts => {
      let folder=rootFolder;
      parts.forEach((name,index) => {
        const path=parts.slice(0,index+1), key=path.join('/');
        if (!folderByPath.has(key)) {
          const child={id:`d${folders.length}`,name,path,parent:folder,children:[],files:[],depth:index+1,x:0,y:0,width:0,height:0,element:null};
          folder.children.push(child); folderByPath.set(key,child); folders.push(child);
        }
        folder=folderByPath.get(key);
      });
      return folder;
    };

    const short = value => String(value).length > 38 ? String(value).slice(0,36) + '…' : String(value);
    const addNode = (file, kind, label, data, qualified = null) => {
      const node = {id:`n${sequence++}`, file, kind, label, data, qualified, localX:0, localY:0, element:null};
      file.nodes.push(node); nodes.push(node);
      if (qualified) symbols.set(qualified, node);
      if (!symbols.has(label)) symbols.set(label, node);
      return node;
    };
    const nestedCalls = calls => {
      const result = [];
      const visit = call => {
        if (!call || !call.object) return;
        result.push(call);
        (call.args || []).forEach(arg => {
          if (arg.value && arg.value.type === 'call') visit(arg.value);
        });
      };
      (calls || []).forEach(visit);
      return result;
    };
    const moduleNameOf = data => data.name==='__init__'
      ? (data.path || '__init__')
      : [data.path,data.name].filter(Boolean).join('.');

    (source.body || []).forEach(wrapper => {
      const data = wrapper.file || {};
      const moduleName = moduleNameOf(data);
      const directory = ensureFolder(pathPartsOf(data));
      const file = {id:`f${files.length}`, label:`${data.name || 'unknown'}.py`, data, directory, nodes:[], x:0, y:0, width:fileWidth, height:0, element:null};
      files.push(file); directory.files.push(file);
      (data.classes || []).forEach(item => {
        const classNode=addNode(file, 'class', item.name, item, item.name);
        symbols.set(`${moduleName}.${item.name}`,classNode);
        (item.methods || []).forEach(method => {
          const methodNode=addNode(file, 'method', `${item.name}.${method.name}`, method, `${item.name}.${method.name}`);
          symbols.set(`${moduleName}.${item.name}.${method.name}`,methodNode);
        });
      });
      (data.functions || []).forEach(item => {
        const functionNode=addNode(file, 'function', item.name, item, item.name);
        symbols.set(`${moduleName}.${item.name}`,functionNode);
      });
      (data.constants || []).forEach(item => {
        const constantNode=addNode(file, 'constant', item.name, item, item.name);
        symbols.set(`${moduleName}.${item.name}`,constantNode);
      });
      const moduleNode=addNode(file, 'module', 'Код модуля', {calls:data.calls || [],imports:data.imports || []}, `${moduleName}.__module__`);
      moduleNodes.set(moduleName,moduleNode);
      file.height = headerHeight + Math.max(1, file.nodes.length) * cellHeight + 18;
      file.nodes.forEach((node, index) => {
        node.localX = 18;
        node.localY = headerHeight + 12 + index * cellHeight;
      });
    });

    const resolveTarget = object => {
      if (typeof object !== 'string' || !object) return null;
      if (symbols.has(object)) return symbols.get(object);
      if (object.endsWith('.__init__')) return symbols.get(object.slice(0,-9)) || null;
      const parts = object.split('.');
      return symbols.get(parts.slice(-2).join('.')) || symbols.get(parts[parts.length-1]) || null;
    };
    const typeNames = value => {
      if (typeof value === 'string') {
        return value.split(/[^A-Za-zА-Яа-яЁё_\d.]+/).filter(Boolean);
      }
      if (!value || typeof value !== 'object') return [];
      return [...new Set(Object.values(value).flatMap(typeNames))];
    };
    const addRelation = (from, to, label) => {
      if (!from || !to || from === to) return;
      const existing = relations.find(edge => edge.from === from && edge.to === to && edge.label === label);
      if (existing) existing.count += 1; else relations.push({from,to,label,count:1});
    };
    files.forEach(file => {
      (file.data.classes || []).forEach(item => {
        const classNode = symbols.get(item.name);
        const parents = Array.isArray(item.parent) ? item.parent : [item.parent];
        parents.filter(Boolean).forEach(parent => addRelation(classNode, resolveTarget(String(parent)), 'наследует'));
        (item.fields || []).forEach(field => {
          typeNames(field.type).forEach(type => {
            addRelation(classNode, resolveTarget(type), `поле ${field.name}`);
          });
        });
        (item.methods || []).forEach(method => {
          const caller = symbols.get(`${item.name}.${method.name}`);
          nestedCalls(method.calls).forEach(call => addRelation(caller, resolveTarget(call.object), 'вызывает'));
        });
      });
      (file.data.functions || []).forEach(item => {
        const caller = symbols.get(item.name);
        nestedCalls(item.calls).forEach(call => addRelation(caller, resolveTarget(call.object), 'вызывает'));
      });
      const moduleNode = symbols.get(`${moduleNameOf(file.data)}.__module__`);
      nestedCalls(file.data.calls).forEach(call => addRelation(moduleNode, resolveTarget(call.object), 'вызывает'));
      (file.data.imports || []).forEach(item => {
        if (item.from_lib) return;
        const exactName=[item.path,item.object].filter(Boolean).join('.');
        const importedModule=moduleNodes.get(item.path);
        const importsWholeModule=item.path && item.object===item.path.split('.').pop();
        const target=symbols.get(exactName)
          || (importsWholeModule ? importedModule : null)
          || resolveTarget(item.object)
          || importedModule;
        addRelation(moduleNode,target,'импортирует');
      });
    });

    const folderPadding = 26, folderTitleHeight = 48, layoutGap = 30, sectionGap = 38;
    const gridLayout = items => {
      if (!items.length) return {width:0,height:0,positions:new Map()};
      const columns=Math.max(1,Math.ceil(Math.sqrt(items.length))), positions=new Map();
      let y=0, width=0;
      for (let start=0; start<items.length; start+=columns) {
        const row=items.slice(start,start+columns), rowHeight=Math.max(...row.map(item=>item.height));
        let x=0;
        row.forEach(item => { positions.set(item.id,{x,y}); x+=item.width+layoutGap; });
        width=Math.max(width,x-layoutGap); y+=rowHeight+layoutGap;
      }
      return {width,height:y-layoutGap,positions};
    };
    const layoutFolder = folder => {
      folder.children.forEach(layoutFolder);
      const fileGrid=gridLayout(folder.files), childGrid=gridLayout(folder.children);
      const hasBoth=fileGrid.height && childGrid.height;
      folder.filePositions=fileGrid.positions; folder.childPositions=childGrid.positions;
      folder.fileGridHeight=fileGrid.height;
      folder.width=Math.max(260,fileGrid.width,childGrid.width)+folderPadding*2;
      folder.height=folderTitleHeight+folderPadding+fileGrid.height+(hasBoth?sectionGap:0)+childGrid.height+folderPadding;
    };
    const positionFolder = (folder,x,y) => {
      folder.x=x; folder.y=y;
      const contentX=x+folderPadding, fileY=y+folderTitleHeight+folderPadding;
      folder.files.forEach(file => { const p=folder.filePositions.get(file.id); file.x=contentX+p.x; file.y=fileY+p.y; });
      const childY=fileY+(folder.files.length?folder.fileGridHeight+sectionGap:0);
      folder.children.forEach(child => { const p=folder.childPositions.get(child.id); positionFolder(child,contentX+p.x,childY+p.y); });
    };
    layoutFolder(rootFolder); positionFolder(rootFolder,40,40);

    folders.forEach(folder => {
      const group=document.createElementNS(ns,'g'); group.classList.add('directory-group'); group.dataset.depth=folder.depth;
      const frame=document.createElementNS(ns,'rect'); frame.classList.add('directory-frame'); frame.setAttribute('width',folder.width); frame.setAttribute('height',folder.height); frame.setAttribute('rx',14);
      const titleBg=document.createElementNS(ns,'rect'); titleBg.classList.add('directory-title-bg'); titleBg.setAttribute('x',14); titleBg.setAttribute('y',10); titleBg.setAttribute('width',Math.min(folder.width-28,Math.max(145,folder.name.length*9+32))); titleBg.setAttribute('height',29); titleBg.setAttribute('rx',7);
      const title=document.createElementNS(ns,'text'); title.classList.add('directory-title'); title.setAttribute('x',26); title.setAttribute('y',30); title.textContent=folder.depth ? `📁 ${folder.name}` : '📁 Корень проекта';
      group.append(frame,titleBg,title); directoriesLayer.append(group); folder.element=group;
      group.addEventListener('pointerdown',event => startFolderDrag(event,folder));
      group.addEventListener('click',event => {
        event.stopPropagation();
        if (folder.suppressClick) { folder.suppressClick=false; return; }
        showDetails({label:folder.path.join('/') || 'Корень проекта',data:{path:folder.path,files:folder.files.map(file=>file.label)},element:group},'Каталог',event.clientX,event.clientY);
      });
    });
    relations.forEach(edge => {
      const group = document.createElementNS(ns,'g');
      const line = document.createElementNS(ns,'line'); line.classList.add('relation');
      const label = document.createElementNS(ns,'text'); label.classList.add('relation-label');
      label.textContent = edge.label + (edge.count > 1 ? ` ×${edge.count}` : '');
      group.append(line,label); relationsLayer.append(group); edge.line=line; edge.text=label;
    });
    files.forEach(file => {
      const group = document.createElementNS(ns,'g'); group.classList.add('file-group');
      const frame = document.createElementNS(ns,'rect'); frame.classList.add('file-frame'); frame.setAttribute('width',file.width); frame.setAttribute('height',file.height); frame.setAttribute('rx',10);
      const header = document.createElementNS(ns,'path'); header.classList.add('file-header'); header.setAttribute('d',`M0 10 Q0 0 10 0 H${file.width-10} Q${file.width} 0 ${file.width} 10 V${headerHeight} H0 Z`);
      const title = document.createElementNS(ns,'text'); title.classList.add('file-title'); title.setAttribute('x',16); title.setAttribute('y',29); title.textContent=file.label;
      const count = document.createElementNS(ns,'text'); count.classList.add('file-count'); count.setAttribute('x',file.width-14); count.setAttribute('y',29); count.textContent=`${file.nodes.length} узл.`;
      group.append(frame,header,title,count); filesLayer.append(group); file.element=group;
      group.addEventListener('pointerdown',event => startFileDrag(event,file));
      group.addEventListener('click',event => { event.stopPropagation(); showDetails(file,'Файл',event.clientX,event.clientY); });
      file.nodes.forEach(node => {
        const element = document.createElementNS(ns,'g'); element.classList.add('node'); element.dataset.kind=node.kind;
        const shape = document.createElementNS(ns,'rect'); shape.classList.add('node-shape'); shape.setAttribute('width',cellWidth); shape.setAttribute('height',42); shape.setAttribute('rx',7);
        const label = document.createElementNS(ns,'text'); label.classList.add('node-label'); label.setAttribute('x',cellWidth/2); label.setAttribute('y',18); label.textContent=short(node.label);
        const kind = document.createElementNS(ns,'text'); kind.classList.add('node-kind'); kind.setAttribute('x',cellWidth/2); kind.setAttribute('y',34); kind.textContent=({class:'класс',function:'функция',method:'метод',constant:'константа',module:'код модуля'})[node.kind];
        element.append(shape,label,kind); nodesLayer.append(element); node.element=element;
        element.addEventListener('pointerdown',event => event.stopPropagation());
        element.addEventListener('click',event => { event.stopPropagation(); showDetails(node,kind.textContent,event.clientX,event.clientY); });
      });
    });

    const nodePoint = node => ({x:node.file.x+node.localX+cellWidth/2,y:node.file.y+node.localY+21});
    const render = () => {
      viewport.setAttribute('transform',`translate(${transform.x} ${transform.y}) scale(${transform.k})`);
      folders.forEach(folder => folder.element.setAttribute('transform',`translate(${folder.x} ${folder.y})`));
      files.forEach(file => {
        file.element.setAttribute('transform',`translate(${file.x} ${file.y})`);
        file.nodes.forEach(node => node.element.setAttribute('transform',`translate(${file.x+node.localX} ${file.y+node.localY})`));
      });
      relations.forEach(edge => {
        const a=nodePoint(edge.from), b=nodePoint(edge.to), dx=b.x-a.x, dy=b.y-a.y;
        const boundaryScale=1/Math.max(Math.abs(dx)/(cellWidth/2),Math.abs(dy)/21,0.0001);
        const x1=a.x+dx*boundaryScale, y1=a.y+dy*boundaryScale;
        const x2=b.x-dx*boundaryScale, y2=b.y-dy*boundaryScale;
        edge.line.setAttribute('x1',x1); edge.line.setAttribute('y1',y1); edge.line.setAttribute('x2',x2); edge.line.setAttribute('y2',y2);
        edge.text.setAttribute('x',(x1+x2)/2); edge.text.setAttribute('y',(y1+y2)/2-5);
      });
    };
    const clearSelection = () => {
      if (selected && selected.element) selected.element.classList.remove('selected');
      selected=null;
    };
    const showDetails = (item,kind,clientX,clientY) => {
      clearSelection(); selected=item; if(item.element) item.element.classList.add('selected');
      document.getElementById('detail-title').textContent=item.label;
      document.getElementById('detail-kind').textContent=kind;
      document.getElementById('detail-json').textContent=JSON.stringify(item.data,null,2);
      const box=document.getElementById('stage').getBoundingClientRect();
      details.style.left=`${Math.max(12,Math.min(box.width-422,clientX-box.left+12))}px`;
      details.style.top=`${Math.max(12,Math.min(box.height-370,clientY-box.top+12))}px`;
      details.hidden=false;
    };
    const hideDetails = () => { details.hidden=true; clearSelection(); };
    document.getElementById('close').addEventListener('click',hideDetails);
    svg.addEventListener('click',hideDetails);

    const moveFolder = (folder,dx,dy) => {
      folder.x+=dx; folder.y+=dy;
      folder.files.forEach(file => { file.x+=dx; file.y+=dy; });
      folder.children.forEach(child => moveFolder(child,dx,dy));
    };
    const startFolderDrag = (event,folder) => {
      event.stopPropagation(); event.preventDefault();
      let lastX=event.clientX, lastY=event.clientY, distance=0;
      folder.element.classList.add('dragging');
      const move=e => {
        const screenX=e.clientX-lastX, screenY=e.clientY-lastY;
        if (!screenX && !screenY) return;
        distance+=Math.hypot(screenX,screenY);
        moveFolder(folder,screenX/transform.k,screenY/transform.k);
        lastX=e.clientX; lastY=e.clientY; render();
      };
      const end=() => {
        folder.element.classList.remove('dragging');
        folder.suppressClick=distance>3;
        window.removeEventListener('pointermove',move); window.removeEventListener('pointerup',end); window.removeEventListener('pointercancel',end);
      };
      window.addEventListener('pointermove',move); window.addEventListener('pointerup',end); window.addEventListener('pointercancel',end);
    };
    const startFileDrag = (event,file) => {
      event.stopPropagation(); const start={x:event.clientX,y:event.clientY,fx:file.x,fy:file.y};
      const move=e => { file.x=start.fx+(e.clientX-start.x)/transform.k; file.y=start.fy+(e.clientY-start.y)/transform.k; render(); };
      const end=() => { window.removeEventListener('pointermove',move); window.removeEventListener('pointerup',end); };
      window.addEventListener('pointermove',move); window.addEventListener('pointerup',end);
    };
    svg.addEventListener('pointerdown',event => { pan={x:event.clientX,y:event.clientY,tx:transform.x,ty:transform.y}; svg.setPointerCapture(event.pointerId); svg.classList.add('panning'); });
    svg.addEventListener('pointermove',event => { if(!pan)return; transform.x=pan.tx+event.clientX-pan.x; transform.y=pan.ty+event.clientY-pan.y; render(); });
    svg.addEventListener('pointerup',() => { pan=null; svg.classList.remove('panning'); });
    svg.addEventListener('wheel',event => {
      event.preventDefault(); const rect=svg.getBoundingClientRect(), px=event.clientX-rect.left, py=event.clientY-rect.top;
      const next=Math.min(3,Math.max(.2,transform.k*Math.exp(-event.deltaY*.001)));
      transform.x=px-(px-transform.x)*next/transform.k; transform.y=py-(py-transform.y)*next/transform.k; transform.k=next; render();
    },{passive:false});
    const fit = () => {
      if(!folders.length)return; const rect=svg.getBoundingClientRect();
      const bounds=[...folders,...files];
      const minX=Math.min(...bounds.map(item=>item.x))-35, maxX=Math.max(...bounds.map(item=>item.x+item.width))+35;
      const minY=Math.min(...bounds.map(item=>item.y))-35, maxY=Math.max(...bounds.map(item=>item.y+item.height))+70;
      transform.k=Math.min(1.2,Math.max(.2,Math.min(rect.width/(maxX-minX),rect.height/(maxY-minY))));
      transform.x=(rect.width-(minX+maxX)*transform.k)/2; transform.y=(rect.height-(minY+maxY)*transform.k)/2; render();
    };
    document.getElementById('reset').addEventListener('click',fit);
    document.getElementById('summary').textContent=`${folders.length-1} каталогов · ${files.length} файлов · ${nodes.length} узлов · ${relations.length} связей`;
    render(); requestAnimationFrame(fit);
    } catch (error) {
      const message=document.createElement('div'); message.className='render-error'; message.setAttribute('role','alert');
      message.textContent=`Не удалось построить граф: ${error instanceof Error ? error.message : String(error)}`;
      document.getElementById('stage').append(message); console.error(error);
    }
  })();
  </script>
</body>
</html>
'''


if __name__ == "__main__":
    raise SystemExit(_main())
