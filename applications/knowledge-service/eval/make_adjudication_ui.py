# -*- coding: utf-8 -*-
"""
把人工裁决集模板渲染成一个**离线单文件标注页**（Phase C2 meta-eval 的标注辅助 UI）。

动机：`meta_eval_judge.py --from-e2e` 产出的 `adjudication_template.jsonl` 每行内嵌
context/answer/reference 明文，直接手改 JSONL 既易错又难读。本脚本把整批条目注入一个
自包含 HTML（无外链、可双击离线打开），逐条以卡片呈现「问题 / 命中上下文 / 待评答案 /
参考答案」，右侧两组 0/1/2 单选（faithfulness 忠实度、correctness 正确性）+ 评分细则；
勾选**自动存 localStorage**（刷新/关页不丢），点「导出」下载 `adjudication.jsonl` ——
结构与 `meta_eval_judge.py --adjudication` 期望**完全一致**（保留原 query/context/
answer/reference，仅回填 human.faithfulness/correctness 为整数 0/1/2，未标注仍为 null）。

诚实约定：这只是**录入辅助**，金标准判断仍由人给出；脚本不改写任何模型分、不代填。
产物（HTML、导出 jsonl）含语料明文 → **不入库**（见 .gitignore），仅本工具源码入库。

用法：
  python eval/make_adjudication_ui.py [--template eval/adjudication_template.jsonl] \\
      [--out eval/adjudication_ui.html]
  生成后双击打开 out 文件，标完点「导出 adjudication.jsonl」，存回 eval/adjudication.jsonl：
  python eval/meta_eval_judge.py --adjudication eval/adjudication.jsonl --candidates self
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

DEFAULT_TEMPLATE = "adjudication_template.jsonl"
DEFAULT_OUT = "adjudication_ui.html"


def load_rows(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def embed_json(data: Any) -> str:
    """安全内联进 <script>：转义 < > 防止内容里的 </script> 提前闭合标签（XSS/破页）。"""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e")


def render_html(rows: List[Dict[str, Any]]) -> str:
    data_js = embed_json(rows)
    n = len(rows)
    # 纯模板：CSS/JS 全部内联，离线可用。__DATA__ / __N__ 为注入点。
    return _TEMPLATE.replace("__DATA__", data_js).replace("__N__", str(n))


_TEMPLATE = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>裁决集标注 · RAG judge meta-eval</title>
<style>
  :root{--bg:#0f1115;--card:#171a21;--fg:#e6e6e6;--mut:#9aa4b2;--line:#2a2f3a;--acc:#4c8dff;--ok:#3fb950;--warn:#d29922;}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.6 -apple-system,"Segoe UI",Roboto,"Microsoft YaHei",sans-serif}
  header{position:sticky;top:0;z-index:5;background:rgba(15,17,21,.95);backdrop-filter:blur(6px);border-bottom:1px solid var(--line);padding:12px 20px;display:flex;gap:16px;align-items:center;flex-wrap:wrap}
  header h1{font-size:16px;margin:0}
  .prog{font-variant-numeric:tabular-nums;color:var(--mut)}
  .bar{flex:1;min-width:120px;height:6px;background:var(--line);border-radius:3px;overflow:hidden}
  .bar>i{display:block;height:100%;background:var(--acc);width:0}
  button{cursor:pointer;border:1px solid var(--line);background:var(--card);color:var(--fg);padding:7px 14px;border-radius:8px;font-size:13px}
  button.primary{background:var(--acc);border-color:var(--acc);color:#fff}
  details{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 12px;margin:14px 20px 0}
  summary{cursor:pointer;color:var(--mut)}
  .rubric td,.rubric th{padding:4px 8px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:13px}
  main{padding:16px 20px 80px;max-width:1180px;margin:0 auto}
  .card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin:14px 0}
  .card.done{border-color:var(--ok)}
  .qid{color:var(--mut);font-size:12px;margin-bottom:6px}
  .q{font-size:16px;font-weight:600;margin-bottom:12px}
  .grid{display:grid;grid-template-columns:1fr 320px;gap:18px}
  @media(max-width:860px){.grid{grid-template-columns:1fr}}
  .pane h4{margin:0 0 4px;font-size:12px;color:var(--mut);font-weight:600;text-transform:uppercase;letter-spacing:.04em}
  pre{white-space:pre-wrap;word-break:break-word;background:#0c0e13;border:1px solid var(--line);border-radius:8px;padding:10px;max-height:220px;overflow:auto;margin:0 0 12px;font:13px/1.55 ui-monospace,Consolas,monospace}
  .ctx{max-height:300px}
  .marks{display:flex;flex-direction:column;gap:14px}
  .mk{border:1px solid var(--line);border-radius:10px;padding:10px}
  .mk b{display:block;margin-bottom:6px;font-size:13px}
  .mk .hint{color:var(--mut);font-weight:400;font-size:11px}
  label.r{display:inline-flex;align-items:center;gap:5px;margin-right:14px;cursor:pointer}
  .tag{font-size:12px;color:#fff;background:var(--acc);border-radius:6px;padding:2px 8px}
  .nav{display:flex;gap:10px;align-items:center;margin-bottom:4px}
  footer{position:fixed;bottom:0;left:0;right:0;background:rgba(15,17,21,.95);border-top:1px solid var(--line);padding:10px 20px;display:flex;gap:14px;align-items:center}
</style>
</head>
<body>
<header>
  <h1>裁决集标注 <span class="tag">judge meta-eval</span></h1>
  <span class="prog" id="prog">0/__N__</span>
  <div class="bar"><i id="barfill"></i></div>
  <button id="onlyUnlabeled">只看未标</button>
</header>

<details>
  <summary>评分细则（0 / 1 / 2 三档，两维各打一次）</summary>
  <table class="rubric">
    <tr><th>维度</th><th>2</th><th>1</th><th>0</th></tr>
    <tr><td><b>faithfulness 忠实度</b><br><span class="hint">答案是否只依据「命中上下文」、无编造</span></td>
        <td>完全有据，无幻觉</td><td>大体有据，个别点缺上下文支撑</td><td>明显编造 / 与上下文矛盾</td></tr>
    <tr><td><b>correctness 正确性</b><br><span class="hint">对照「参考答案」答得对不对、全不全</span></td>
        <td>与参考一致且完整</td><td>部分正确 / 有遗漏</td><td>错误 / 答非所问</td></tr>
  </table>
  <div class="hint">提示：以人工判断为准，模型分仅供参考、本页不展示也不代填。可用键盘 1/2/3 选当前维度（可选）。</div>
</details>

<main id="main"></main>

<footer>
  <button class="primary" id="export">导出 adjudication.jsonl</button>
  <button id="reset">清空标注</button>
  <span class="prog" id="foot">—</span>
</footer>

<script>
const DATA = __DATA__;
const LS_KEY = "adjudication_labels_v1";
let labels = {};
try { labels = JSON.parse(localStorage.getItem(LS_KEY) || "{}"); } catch(e){ labels = {}; }
let onlyUnlabeled = false;

const DIMS = [["faithfulness","忠实度"],["correctness","正确性"]];

function esc(s){return (s===""||s==null)?"—":String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));}

function isDone(row){const l=labels[row.qid]||{};return l.faithfulness!=null && l.correctness!=null;}

function save(){localStorage.setItem(LS_KEY, JSON.stringify(labels));updateProg();}

function updateProg(){
  const done=DATA.filter(isDone).length;
  document.getElementById("prog").textContent = done+"/"+DATA.length;
  document.getElementById("barfill").style.width = (100*done/DATA.length)+"%";
  document.getElementById("foot").textContent = "已标注 "+done+" / "+DATA.length+"（未标条目导出时 human 保持 null，不影响对比）";
}

function radio(row,dim){
  const cur=(labels[row.qid]||{})[dim];
  return [0,1,2].map(v=>{
    const id=row.qid+"_"+dim+"_"+v;
    const checked=(cur===v)?"checked":"";
    return `<label class="r"><input type="radio" name="${row.qid}_${dim}" id="${id}" value="${v}" ${checked}> ${v}</label>`;
  }).join("");
}

function card(row,i){
  const done=isDone(row)?" done":"";
  const cols=DIMS.map(([d,zh])=>`<div class="mk"><b>${d} <span class="hint">${zh}</span></b>${radio(row,d)}</div>`).join("");
  return `<div class="card${done}" id="card_${i}" data-qid="${row.qid}">
    <div class="qid">#${i+1} · ${esc(row.qid)}</div>
    <div class="q">${esc(row.query)}</div>
    <div class="grid">
      <div class="pane">
        <h4>待评答案 answer</h4><pre>${esc(row.answer)}</pre>
        <h4>参考答案 reference</h4><pre>${esc(row.reference)}</pre>
      </div>
      <div class="pane">
        <h4>命中上下文 context</h4><pre class="ctx">${esc(row.context)}</pre>
        <div class="marks">${cols}</div>
      </div>
    </div>
  </div>`;
}

function render(){
  const main=document.getElementById("main");
  const rows=DATA.map((r,i)=>({r,i})).filter(({r})=>!onlyUnlabeled||!isDone(r));
  main.innerHTML=rows.map(({r,i})=>card(r,i)).join("");
  main.querySelectorAll("input[type=radio]").forEach(el=>{
    el.addEventListener("change",()=>{
      const card = el.closest(".card"); const qid = card.dataset.qid;
      const dim = el.name.endsWith("faithfulness") ? "faithfulness" : "correctness";
      labels[qid] = labels[qid] || {}; labels[qid][dim] = parseInt(el.value, 10);
      card.classList.toggle("done", isDone({qid}));
      save();
    });
  });
  updateProg();
}

function doExport(){
  const out=DATA.map(r=>{
    const l=labels[r.qid]||{};
    return {qid:r.qid, query:r.query, context:r.context, answer:r.answer,
            reference:r.reference, tags:r.tags,
            human:{faithfulness:l.faithfulness!=null?l.faithfulness:null,
                   correctness:l.correctness!=null?l.correctness:null}};
  });
  const body=out.map(o=>JSON.stringify(o)).join("\n");
  const blob=new Blob([body],{type:"application/x-ndjson"});
  const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download="adjudication.jsonl";
  document.body.appendChild(a);a.click();a.remove();
}

document.getElementById("export").onclick=doExport;
document.getElementById("onlyUnlabeled").onclick=function(){onlyUnlabeled=!onlyUnlabeled;this.textContent=onlyUnlabeled?"显示全部":"只看未标";render();};
document.getElementById("reset").onclick=function(){if(confirm("确认清空所有本地标注？")){labels={};save();render();}};
render();
</script>
</body>
</html>
"""


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把裁决集模板渲染成离线单文件标注页（Phase C2 meta-eval 录入辅助）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--template", default=str(_PROJECT_ROOT / "eval" / DEFAULT_TEMPLATE),
                        help="待标注模板 jsonl（meta_eval_judge --from-e2e 产出）")
    parser.add_argument("--out", default=str(_PROJECT_ROOT / "eval" / DEFAULT_OUT),
                        help="输出 HTML 路径（双击浏览器打开）")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    tpl = Path(args.template)
    if not tpl.exists():
        print(f"错误：模板不存在：{tpl}", file=sys.stderr)
        print("  先跑 `python eval/meta_eval_judge.py --from-e2e <run>/e2e_per_query.jsonl --sample 30`。", file=sys.stderr)
        return 1
    rows = load_rows(tpl)
    if not rows:
        print("错误：模板为空。", file=sys.stderr)
        return 1
    missing_qid = [i for i, r in enumerate(rows) if r.get("qid") in (None, "")]
    if missing_qid:
        print(f"错误：第 {missing_qid} 行缺 qid（标注结果无法按条对齐）。", file=sys.stderr)
        return 1
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(rows), encoding="utf-8")
    print(f"[adjudication-ui] {len(rows)} 条 → {out}")
    print("[adjudication-ui] 双击打开该文件标注；标完点「导出 adjudication.jsonl」，存到 eval/adjudication.jsonl，再跑：")
    print("  python eval/meta_eval_judge.py --adjudication eval/adjudication.jsonl --candidates self")
    return 0


if __name__ == "__main__":
    sys.exit(main())
