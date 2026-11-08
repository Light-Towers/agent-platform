# ⚠ 入参改成 **CSV 单串**（刀㊶）：旧形 `[string[]]$FilesOverride` 跨 `powershell -File` 调用时只绑走第一项
# （本批实踩：递三个文件 ⇒ 子脚本报“找不到位置参数”直接死，门件那一格拿到的是空输出而不是红）。
# 与 ts-provability 的 $FilesCsv 同一口径：边界上只走字符串，数组在进程内自己拆。
param([string]$FilesOverrideCsv = '')
$ErrorActionPreference = 'Stop'
Set-Location d:\Study\github\agent-platform
# 本工具扫描面的文件表（不写件数——那句从第九批挂到现在，是射程小于声称那一型；门件 B2b 格从源码里**派生**
# 这份表来对账“本刀改的入库文档是不是都被扫了”，所以这里加一件就自动多防一件）。
$files = @(
  'docs/README.md',
  'AGENTS.md',
  'docs/plans/plan-web-visual-design-2026-10-30.md',
  'docs/plans/plan-web-frontend-minimal-core-2026-10-29.md',
  'docs/plans/plan-node-clock-time-source-2026-11-04.md',
  'docs/plans/plan-gate-attribution-and-candidate-tree-commit-2026-11-05.md',
  'docs/plans/plan-web-auth-user-minimal-2026-11-05.md',
  'docs/operations/observability-pitfalls.md',
  'docs/operations/evidence/2026-10-30-web-visual-references/readings.md',
  'web/README.md',
  # 刀㊵（PR-2c）扩面：先量旧债再进面（两件的进面前读数在 k62-facetarget-20261106-065604.txt ——
  # T1=1/T2=1/T4=1），同批清完才加进来，不把别人的债静默计到本刀头上（处置口径见上面 ARCHITECTURE.md 那条）。
  'deploy/k8s/README.md',
  'docs/operations/minimal-release-runbook.md',
  # 刀 k71（2026-11-06）进面两件错误契约方案件。它们是本刀批准依据本体（G1），而门件 B2b
  # 从本表派生扫描面与「本刀改的入库 .md」对账 —— 不进来就是 TYPO-FACE-UNCOVERED。
  # 进面前读数按在册规矩先单量：T1=0/T2=0/T3=0/T5=0，**T4=2**（两件破表：行内 code span
  # 里的 `|` 照样切列）—— 已同批清完才加面，件 k71-typo-pretarget-20261106-151519.txt（前）
  # 与 k71-typo-posttarget-20261106-153015.txt（后 T4=0）。
  'docs/plans/plan-error-contract-alignment-2026-11-04.md',
  'docs/plans/plan-error-contract-staged-split-2026-11-06.md',
  # 刀 k71/P3（2026-11-06）按在册「先清债再扩面」的处置收口：ARCHITECTURE.md 那条 T2=1 是第 44 行
  # 把 ADR 路径写成不带后缀的 docs/adr/0005（T2 判 MISSING），已就地补全完整文件名；两份各单量
  # T1..T5 全 0 之后才加进默认面，不把别人的债静默计到本刀头上（单量件 p3-typo-pretarget-20261106.txt）。
  'ARCHITECTURE.md',
  'scripts/evidence/README.md',
  # 刀 k76（2026-11-06）进面：本刀改了 ADR-0010（新开 §7），B2b 那格从本表派生扫描面与
  # 「本刀改的入库 .md」对账 ⇒ 不进来就是 TYPO-FACE-UNCOVERED（本轮门件当场咬到，件
  # e26-gate-00-20261106-205559-gate-fill.txt）。进面前先单量：T1..T5 全 0、forbidden=0、rc=0
  # （件 k76-adr-facetarget.txt）⇒ 无旧债，不欠「同批清债」那一步。**只进本刀改的这一件**：
  # 把整个 docs/adr/ 一次拉进面会把别人历史文档的债静默计到本刀头上（上面两条注释同一条纪律）。
  'docs/adr/0010-ui-stack-selection.md',
  # 刀 48（2026-11-07）进面：本批把审核件 add -N 申报进 own 面（face_basis 的 NEW-NOT-INTENT-ADDED
  # 齿要求 untracked 先申报），B2b 随即咬 TYPO-FACE-UNCOVERED。进面前单量读数见件
  # k80-typo-selfscan3.txt（全 0，无旧债）。
  'docs/plans/review-error-contract-g2-2026-11-07.md'
)
# Optional override: lets a POSITIVE CONTROL run the REAL tool against a synthetic sample instead of
# re-implementing the matcher elsewhere (a copied matcher proves nothing about this file).
if ($FilesOverrideCsv -ne '') { $files = @($FilesOverrideCsv -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }) }
# fail-closed：面里有路径不存在 ⇒ 当场红并退。否则“路径写错”与“这一刀没改文档”在读数上同形（都是 0 命中）。
$noFace = @($files | Where-Object { -not (Test-Path -LiteralPath $_) })
Write-Output ('scan face (' + $files.Count + ' files): ' + ($files -join ' , '))
if ($noFace.Count -gt 0) {
  Write-Output ('<<< TYPO-FACE-NOT-FOUND: ' + ($noFace -join ' , ') + ' (a face entry git/fs cannot see scans 0 lines = a silent bypass, not a clean pass)')
  Write-Output 'TYPO_RC=1'
  exit 1
}

Write-Output "=== T1 实踩错字型词表（只防本会话历史真踩过的型，不是完备检查）==="
$typos = @(
  '木身','木机','幮','以经','因该','做为','这祥','那一磨','即然','自罚','复稍','终值现值',
  '检查检','不din','门今','判剧','兆底','兜低','派生自-source',
  '拓出','拓开','口讼','捾','你栏行'
)
$h1 = 0
foreach ($f in $files) {
  $i = 0
  foreach ($line in (Get-Content $f -Encoding utf8)) {
    $i++
    foreach ($t in $typos) {
      if ($line -match [regex]::Escape($t)) { $h1++; Write-Output "  HIT ${f}:${i}  [$t]" }
    }
  }
}

# T1-cp (batch-11): code-point shaped probes folded into T1. The body stays ASCII on purpose --
# same rule as cp-sweep9.ps1: a probe must not contain the glyph it hunts, because this session's
# write pipeline has been observed to distort a single CJK char (that is how the typos got in).
# The needle is therefore BUILT from the code point at runtime.
#   forbidden = must never appear in these files; each entry is a typo this session actually committed.
#     Entries are either a single code point OR a HYPHEN-JOINED SEQUENCE, because the shape actually
#     observed on 2026-10-31 was TWO chars: the word U+53E3+U+5F84 came out as U+53E3+U+52B2. Asserting
#     U+52B2 alone is WRONG -- it is a legitimate character in a common three-char idiom, and the very
#     first run of this face produced a false positive on it (batch-11, §18.6 row 7).
#   review    = a hit is NOT a violation until its coordinates are read -- U+62D3 is a legitimate
#     character inside the network term U+62D3+U+6251, and U+52B2 likewise; neither can be a hard zero.
# batch-32 appendix: U+62C4 kept coming out where U+6284 (transcribe) belongs -- 7 live occurrences
#   across two files, all inside three fixed two-char shapes. A single-char assertion is WRONG here:
#   U+62C4 legitimately appears twice in these files as the *named* wrong char inside our own
#   self-fault tables, and binding those would force a future reader to delete the record to go
#   green. So the needles are the shapes actually observed, kept ASCII on purpose (same rule as
#   above: a probe body must not contain the glyph it hunts):
#     624B-62C4 = "hand + wrong char"  |  62C4-6570 = "wrong char + number"
#     62C4-8FDB = "wrong char + into"
# batch-34 (刀㊶)：**同一个字第五次复发，而上面三枚形状盖不住它**。工单件第三十四批行初稿写的是
#   62C4-9519（"wrong char + mistake"，语义上该处是 U+6284 transcribe），它是被**读 diff 回显**看见的
#   而不是被齿看见的 ⇒ 补一枚已观察到的形状（加严方向），而不是把单字 U+62C4 抬成硬 0（那会咬到
#   自犯表里那些“把错字本身点名登记”的合法自指，逼后人删记录凑绿——与 batch-32 同一口径）。
# batch-34 第二枚（同一轮收尾时）：把「扫描面」递成了「扇描面」（626B 扫 → 6247 扇）。它与上面那型**不同字**
#   但同形状：一次“只是改一句话”的编辑替掉了单个汉字，也是被 diff 回显而非齿看见。扇 是常用字（风扇/一扇），
#   单字不能进 forbidden；而 6247-63CF（扇 + 描）这个二字串**不可能合法出现**，所以只加形状。
$cpForbidden = @('5F13', '8DF1', '53E3-52B2', '624B-62C4', '62C4-6570', '62C4-8FDB', '62C4-9519', '6247-63CF')
$cpReview = @('62D3', '52B2', '62C4')
$cpForbiddenTotal = 0
foreach ($cp in $cpForbidden) {
  $needle = ( ($cp -split '-') | ForEach-Object { [string][char][Convert]::ToInt32($_, 16) } ) -join ''
  $pat = [regex]::Escape($needle)
  foreach ($f in $files) {
    $i = 0
    foreach ($line in (Get-Content $f -Encoding utf8)) {
      $i++
      $m = ([regex]::Matches($line, $pat)).Count
      if ($m -gt 0) { $h1 += $m; $cpForbiddenTotal += $m; Write-Output "  HIT-CP ${f}:${i}  [U+$cp x$m]" }
    }
  }
}
$cpReviewTotal = 0
foreach ($cp in $cpReview) {
  $needle = [string][char][Convert]::ToInt32($cp, 16)
  $pat = [regex]::Escape($needle)
  foreach ($f in $files) {
    $i = 0
    foreach ($line in (Get-Content $f -Encoding utf8)) {
      $i++
      $m = ([regex]::Matches($line, $pat)).Count
      if ($m -gt 0) { $cpReviewTotal += $m; Write-Output "  REVIEW-CP ${f}:${i}  [U+$cp x$m]  (须读坐标判正词/错字，不计入 T1)" }
    }
  }
}
"T1 probes: 词串=" + $typos.Count + ' 码点 forbidden=' + $cpForbiddenTotal + ' review=' + $cpReviewTotal
"T1 hits=$h1"

Write-Output "=== T2 反引号内「路径状」字符串的存在性（扩展到 web/ packages/ applications/ scripts/）==="
$h2 = 0
foreach ($f in $files) {
  $raw = Get-Content $f -Raw
  $refs = ([regex]::Matches($raw, '(?m)`([^`\r\n]+)`') | ForEach-Object { $_.Groups[1].Value }) |
    Where-Object { $_ -match '^(web|packages|applications|scripts|docs|eval|tests)/[A-Za-z0-9._/\-]+$' -and $_ -notmatch '\*$' -and $_ -notmatch '\.mX$' }
  foreach ($r in ($refs | Sort-Object -Unique)) {
    if (-not (Test-Path $r)) {
      # 允许指向 gitignored 取证目录（.tmp-scratch 不在库内形状；这里显式列出已知例外）
      if ($r -match '^\.tmp-scratch') { continue }
      $h2++; Write-Output "  MISSING $f  ->  $r"
    }
  }
}
"T2 hits=$h2"

Write-Output "=== T3 每行反引号奇偶（奇数=反引号未闭合，表格形状错的前兆；跳代码围栏）==="
$h3 = 0
foreach ($f in $files) {
  $i = 0
  $inFence = $false
  foreach ($line in (Get-Content $f -Encoding utf8)) {
    $i++
    if ($line -match '^\s*```') { $inFence = -not $inFence; continue }
    if ($inFence) { continue }
    $n = ([regex]::Matches($line, '`')).Count
    if ($n % 2 -ne 0) { $h3++; Write-Output "  ODD ${f}:${i}  backticks=$n" }
  }
}
"T3 hits=$h3"

Write-Output "=== T4 表格行的竖线形状（只计**未转义**的 |，跳代码围栏；got!=expect 就是破表）==="
$h4 = 0
foreach ($f in $files) {
  $lines = Get-Content $f -Encoding utf8
  $i = 0
  $inFence = $false
  $hdrCols = -1
  foreach ($line in $lines) {
    $i++
    if ($line -match '^\s*```') { $inFence = -not $inFence; $hdrCols = -1; continue }
    if ($inFence) { continue }
    if ($line -match '^\|' -and $line -match '\|\s*$') {
      $c = ([regex]::Matches($line, '(?<!\\)\|')).Count
      if ($hdrCols -lt 0) { $hdrCols = $c }
      elseif ($c -ne $hdrCols) { $h4++; Write-Output "  COLS ${f}:${i}  got=$c expect=$hdrCols" }
    } else {
      $hdrCols = -1
    }
  }
}
"T4 hits=$h4"

Write-Output "=== T5 变异脚本格标签 vs 文档抄写（错字从工具爬进文档那一型）==="
$scriptRaw = Get-Content '.tmp-scratch/ap-visual/mutate-v1.mjs' -Raw
$labels = ([regex]::Matches($scriptRaw, "(?m)^\s*\['([^']+)\s*") | ForEach-Object { $_.Groups[1].Value })
"  脚本标签数=" + $labels.Count
$h5 = 0
$docRaw = (Get-Content 'docs/operations/evidence/2026-10-30-web-visual-references/readings.md' -Raw) + (Get-Content 'docs/plans/plan-web-visual-design-2026-10-30.md' -Raw)
foreach ($l in $labels) {
  # 台账/视觉件里以「断言N 标签」或子串形式出现；只校「标签里含中文且文档出现过同一连续 4 字片段」
  $probe = $l
  if ($probe.Length -ge 4) { $probe = $probe.Substring(0, 4) }
  if ($docRaw -notmatch [regex]::Escape($probe)) { $h5++; Write-Output "  LABEL-NOT-IN-DOC $l" }
}
"T5 hits=$h5（0 = 无；>0 只说明该标签未被文档引用，不等于错字）"
