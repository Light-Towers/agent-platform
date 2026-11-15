# ts-provability.ps1 — 不变量检查（刀㊶ 新齿，方案件 docs/plans/plan-node-clock-time-source-2026-11-04.md §5 层 3）。
# 防的是哪一型：账面把「一个时间戳读数」写成事实，而全仓没有任何取证件回答过它（刀㊵ §40.4 行 4 实踩：
# 那行写的三方 date -u 01:08:34 / 01:08:36 在任何件里都 0 命中；结论方向对，证据形状是我编的）。
# 因此本件的判据是**内容可证性**，不是形状：
#   R-1 新增行里的每个 ISO-8601 `T` 形时间戳，必须能在 corpus 里原样 grep 到 ⇒ 否则 UNPROVABLE-TS。
#   R-2 新增行引用到的取件名（kNN-*.txt / eNN-*.txt 这类），必须真的在位 ⇒ 否则 ARTIFACT-NOT-ON-DISK。
#   R-3 corpus 构造不出来（目录不在 / 一个文件都没读到）⇒ TS-CORPUS-EMPTY，**fail-closed**，不退回"当作没引用"。
#   R-4 申报面为空 ⇒ TS-NO-FACE（与门件 A-selftest-0 同一口径：空的输入会把门变成旁路，历史已踩过）。
#   R-5 申报项本身要能在 `git ls-files` 里解析到 ⇒ 否则 TS-FACE-NOT-TRACKED（路径写错与“这一刀没改文档”
#       在读数上同形：都是 0 行可判 ⇒ 静默旁路。递错=假绿，递空=自拒，两者都要响）。
# ⚠ 入参形是 **CSV 单串**而不是数组：门件用 `powershell -File` 调本件时，数组会被展成多个独立 token，
#    子脚本只拿到第一项（其余变成“找不到位置参数”或静默丢弃）⇒ 那一格就只判了面的 1/N。
#    名称用 $FilesCsv 不用 $Files：在册教训——param 与体内变量同名时（PS 变量名大小写不敏感）会被静默强转。
# 零豁免：**没有**「推导项免检」口子。代价与口径写进方案件 §7 末（推导时刻须写成带操作数的界限，不写成 ISO）。
# 盲区（当场声明，不装作已防）：只认 ISO `T` 形；`YYYY-MM-DD HH:MM:SS` 空格形、时长差值、带 `*`/`{}` 的
# 占位件名都不在射程；它也不检查「读数引错了对象」这种语义错配。
param(
    [string]$FilesCsv = '',
    [string]$BaseRef = 'HEAD',
    [string]$CorpusDir = '.tmp-scratch/ap-visual'
)
$ErrorActionPreference = 'Stop'
$Files = @($FilesCsv -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' })
$repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
Set-Location $repo
$ISO = [regex]'(?<![\d:])\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?'
$NAME = [regex]'\b(?:k\d{1,3}|e\d{1,3})-[A-Za-z0-9._\-]+\.(?:txt|log|json|md|ps1|sh|csv|png|svg|bundle|log)\b'
$fails = @()
# ⚠ 合成样本一律运行时拼接（与 scripts/lint_public_mirror.py:_asm 同形）：本件入库之后，源码每一行
#   都成了「账面新增行」，R-1 / R-2 会把夹具里的假时间戳、假件名当事实陈述去 corpus 里找 —— 找得到才怪。
#   拼接只改字面形状：样本值、判据、射程、自测期望全不变，也不给量具开任何豁免口子。
$script:FakeIso = '1999-01-01' + 'T00:00:00'
$script:K99 = 'k99-ts-selftest-'
$script:K98 = 'k98-ts-selftest-'
function Say($s) { Write-Host $s }
# ---- git 调用收敛到**一个出口**（刀㊶ 真面反证当场照出来的坑）：native 命令往 stderr 写一行文本，在
#      $ErrorActionPreference='Stop' + 重定向下会被包成 NativeCommandError 并**终止脚本**。git 的 CRLF
#      advice（"CRLF will be replaced by LF"）走的就是 stderr ⇒ 整把工具死在第一个文件上：rc=1、零输出、
#      一条真判据都没跑。那是「量具自己瞎」而不是「账面被抓」，所以处置有两层，都在本件内：
#   ① stderr 文本 ≠ 失败 ⇒ 调用期间临时降 EAP，rc 才是判据；
#   ② git 真失败不许静默返回空数组（空数组与「这个文件没有新增行」同形 = 静默旁路）⇒ **记录 rc**，
#      由下面 TS-GIT-CMD-FAIL 报红，并由 selftest-6 自证这枚齿能咬。
#   ⚠ 调用点一律写 `-gargs @(...)`：PS 会把命令行里以 `-` 开头的 token（`-U0` / `--`）当**参数名**去解析，
#      在 ValueFromRemainingArguments 上报“找不到参数”⇒ 又一型“调用点没变、参数形状变了”。
$script:gitFail = New-Object System.Collections.ArrayList
function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$gargs)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $out = @(& git @gargs 2>$null)
    $rc = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($rc -ne 0) { [void]$script:gitFail.Add(('git ' + ($gargs -join ' ') + ' rc=' + $rc)) }
    return , @($out)
}

# ---- corpus：本机取件（gitignored）+ 入库取证件。文本合成一块，判定用 Ordinal 子串。
# ⚠ 两处本批实踩的构造陷阱（都是「把齿磨成钝的」那一型）：
#   ① **PS 5.1 的 -Include 配 -LiteralPath 不生效**（它只在 -Path 带通配时参与过滤）。第一版因此读了
#      scratch 目录下的**每一个文件**，包括本件自己的源码 ⇒ selftest-1 的假戳被源码供成“有原文”，
#      这一格就永久变成 yes-man。现在是 -Path 通配 + 代码内扩展名白名单（双保险）。
#   ② **scratch 面不收 .md**：那儿住着 runbook 与文档快照，收了等于允许台账引台账自己（刀㊵ 那条正是
#      “引自己上一行的数”这种型）。入库面只收 .md，且**排除正在被判断的那些件**（见下）。
$extOk = @('.txt', '.log', '.json', '.out')
#   ③ **量具与门件自己的日志不是证据源**：真面反证会把假戳写进 stdout，而 stdout 必落盘成件
#      （`e26-gate-00-*` = 门件聚合日志，`*counterproof*` = 反证记录）。不排除 ⇒ “假戳曾在某份日志里出现过”
#      会把 R-1 磨成恒真。
#      ⚠ 方向性要说清：排除 corpus 只会让本格**更容易报红**（证据源变少），造不出假绿。而“排除有没有失效”
#      不靠自觉——selftest-1 与下面的哨兵闸门机械地复查：哨兵串一旦又出现在 corpus 里，立刻 VACUOUS/红。
$logSkip = @('*provability*', '*counterproof*', '*console*', 'e26-gate-00-*')
function Test-CorpusSkip([string]$n) { foreach ($pat in $logSkip) { if ($n -like $pat) { return $true } }; return $false }
#   ④ **任何“判决自己的记录”都不是证据源**（刀㊶ 真面反证第 1 轮实踩，两个危害同方向）：单独跑量具时把
#      stdout/stderr 落到 corpus 目录 ⇒ （a）句柄被父 shell 占着 → ReadAllText 抛 → `TS-CORPUS-READ-FAIL` 偶发红；
#      （b）**更坏**：能读到的那一轮，假戳就在上一轮自己的 stdout 里 ⇒ R-1 会被“我上一轮也报过这个假戳”
#      喂成恒真。本轮没出现假绿纯属侥幸（正好读失败），侥幸不是机制。
#      ⇒ 两个处置都在量具层：共享读（FileShare.ReadWrite）消除 (a)；**按内容**排除判决日志（行首 `<<< `
#      或 `TS_RC=` / `GATE_RC=` / `TYPO_RC=`）消除 (b)，不靠无穷无尽的临时件名。
#      ⚠ 试过按 mtime 排除 in-flight 件，**实测无效**（同一轮 `inflight-skipped=0` 而 `read-failures=2`）：
#      写句柄在 flush 前不更新 mtime ⇒ 那是一条“看着在过滤、实际从不生效”的规则。记在这儿是为了
#      回答“为什么不用它”，不是备用开关。
#      ⚠ 内容闸门只加在 **scratch（无人评审的本机面）**；入库面（tracked .md）不走它：方案件正文本来就会
#      提到这些标记名（本件 §5 就写着 `UNPROVABLE-TS`），把它们当证据是人工评审过的决定。
$logMarkRe = '(?m)^<<< '
$logMarkLits = @('TS_RC=', 'GATE_RC=', 'TYPO_RC=')
function Test-CorpusSelfLog([string]$t) {
    if ($t -match $logMarkRe) { return $true }
    foreach ($lit in $logMarkLits) { if ($t.Contains($lit)) { return $true } }
    return $false
}
#   共享读：文件被别的进程写着也能读。“读不到”从此只剩权限一类真因，不再与“件名不巧”同形。
# ── 编码面（刀㊶ 第四件期外实踩，本批普查 1274 件）：读_surface_必须匹配写_surface_，否则「件在、数不在」有第三条成因
#   ① `Out-File -Encoding utf8` 写头 + `Tee-Object -Append` 续写 ⇒ 同一个文件**两种编码**，BOM 说的是 UTF-8 而体内是 UTF-16LE
#      ⇒ 按 BOM 选的读者读不到那个数，而人眼 Get-Content 看得见（历史样本 k46-ruff-foreign-20261104-153740.txt
#      的 nul 值 8463/16986；同串 `Found 13 errors.` 按 UTF-8 读 False / 按 UTF-16 读 True ⇒ 本轮机械复现）。
#   ② 普查另有 150 件 **无 BOM 的纯 UTF-16LE**（PowerShell 5.1 重定向默认编码）⇒ 任何 UTF-8 grep 对它们**内容整体不可见**。
#   危害方向要说清：内容不可见只会让 R-1/R-6 **更容易报红**（假红），不会造假绿；但它同时让
#   ④ 那条**内容闸门看不见 UTF-16 里的判决标记** ⇒ 「排除判决日志」这 150 件上从不生效（与 mtime 那条同一型：看着在过滤）。
#   ⇒ 处置：按**字节**读 + 按 BOM/NUL 分布解码；分裂件按**两种解码并集**判（消假红），同时单独计 $script:splitArt 报红（缺陷入账）。
$script:encHist = @{}
$script:splitArt = @()          # 写件管道造成的编码分裂（证据不可核 ⇒ 报红）
$script:binArt = @()            # 真二进制件被扩展名白名单误收（如 chrome-profile-probe 的 LEVELDB .log ⇒ 排除+计数，不报红）
$script:citedSplit = @()        # **被账面引用**且编码分裂的件（只有这一型才是风险：数绑在一个读不出数的件上）
$script:lastEncTag = ''
function Read-SharedBytes([string]$path) {
    $fs = [System.IO.File]::Open($path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
    try {
        $ms = New-Object System.IO.MemoryStream
        $fs.CopyTo($ms)
        return , $ms.ToArray()
    } finally { $fs.Dispose() }
}
function Resolve-BytesToText([byte[]]$b) {
    # 返回 @{ tag=..; text=.. }。tag 是**读数**不是判断：它要回答「这一件的数是用哪种解码读到的」。
    $nulEven = 0; $nulOdd = 0
    for ($i = 0; $i -lt $b.Length; $i++) { if ($b[$i] -eq 0) { if (($i % 2) -eq 0) { $nulEven++ } else { $nulOdd++ } } }
    $nul = $nulEven + $nulOdd
    $utf8 = [System.Text.Encoding]::UTF8
    if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) {
        $body = $utf8.GetString($b, 3, $b.Length - 3)
        # BOM 说 UTF-8 而体内还有 NUL ⇒ 编码分裂（①），判据取两种解码的并集，但 tag 单独标出来
        if ($nul -gt 0) {
            $u16 = [System.Text.Encoding]::Unicode.GetString($b)
            return @{ tag = 'SPLIT-utf8bom+utf16le'; text = ($body + "`n" + $u16) }
        }
        return @{ tag = 'utf8-bom'; text = $body }
    }
    if ($b.Length -ge 2 -and $b[0] -eq 0xFF -and $b[1] -eq 0xFE) { return @{ tag = 'utf16le-bom'; text = [System.Text.Encoding]::Unicode.GetString($b, 2, $b.Length - 2) }
    }
    if ($b.Length -ge 2 -and $b[0] -eq 0xFE -and $b[1] -eq 0xFF) { return @{ tag = 'utf16be-bom'; text = [System.Text.Encoding]::BigEndianUnicode.GetString($b, 2, $b.Length - 2) }
    }
    if ($nul -gt 0) {
        if ($nulOdd -ge (2 * $nulEven)) { return @{ tag = 'utf16le-noBOM'; text = [System.Text.Encoding]::Unicode.GetString($b) }
        }
        if ($nulEven -ge (2 * $nulOdd)) { return @{ tag = 'utf16be-noBOM'; text = [System.Text.Encoding]::BigEndianUnicode.GetString($b) }
        }
        return @{ tag = 'NUL-UNDETERMINED'; text = $utf8.GetString($b) }
    }
    return @{ tag = 'utf8-noBOM'; text = $utf8.GetString($b) }
}
function Read-SharedText([string]$path) {
    $d = Resolve-BytesToText (Read-SharedBytes $path)
    $tag = $d.tag
    $script:lastEncTag = $tag
    if (-not $script:encHist.ContainsKey($tag)) { $script:encHist[$tag] = 0 }
    $script:encHist[$tag] = $script:encHist[$tag] + 1
    if ($tag -eq 'SPLIT-utf8bom+utf16le') { $script:splitArt += (Split-Path -Leaf $path) }
    if ($tag -eq 'NUL-UNDETERMINED') { $script:binArt += (Split-Path -Leaf $path) }
    return $d.text
}
$selfLeaf = Split-Path -Leaf $MyInvocation.MyCommand.Path
function Test-CorpusEligible([System.IO.FileInfo]$fi) {
    return ($extOk -contains $fi.Extension) -and ($fi.Length -le 5MB) -and ($fi.Name -ne $selfLeaf) -and
        (-not (Test-CorpusSkip $fi.Name))
}
$corpusFiles = @()
$corpusBytes = 0
if (Test-Path -LiteralPath $CorpusDir) {
    $corpusFiles = @(Get-ChildItem -Path (Join-Path $CorpusDir '*') -File -Recurse -ErrorAction SilentlyContinue |
            Where-Object { Test-CorpusEligible $_ } | ForEach-Object { $_.FullName })
    foreach ($f in $corpusFiles) { $corpusBytes += (Get-Item -LiteralPath $f).Length }
}
# ⚠ 本批实踩（门件接线当场照出来的）：corpus 里碰上了**门件自己正在写的 console 落盘件**，句柄被外层
# shell 占着 ⇒ ReadAllText 抛异常，而 $ErrorActionPreference='Stop' 让整把工具当场死掉（rc=1、零输出）。
# 两个处置都是改量具本身，不是放宽：
#   ① 运行日志不属证据源 ⇒ 上面 `$logSkip` 加了 `*console*`；
#   ② 单个文件读不到不能让整把工具死（那一格会变成“偶尔盲”），也不能静默跳过（跳过 = corpus 不完整而账面说自
#      己看完了）⇒ 逐件 try/catch + **计数** + 有读不到就 fail-closed 报红。
$readFail = @()
$encExcl = 0
$extHist = (($corpusFiles | ForEach-Object { [System.IO.Path]::GetExtension($_) }) | Group-Object | ForEach-Object { $_.Name + ':' + $_.Count }) -join ' '
# ⚠ corpus **必须排除正在被判断的那些件**：把台账自己当证据源 = 一条编造的戳可以靠“早先我自己也这么写过”
# 自证（而刀㊵ 那条正是这种型：它引的是自己上一行的数）。只拿取件与**其他**入库件当原文依据。
$normFiles = @($Files | ForEach-Object { ($_ -replace '\\', '/') })
$trackedRaw = Invoke-Git -gargs @('ls-files', 'docs/operations', 'docs/plans', 'docs/adr')
$tracked = @($trackedRaw | Where-Object { $_ -match '\.md$' } | ForEach-Object { $_ -replace '\\', '/' } | Where-Object { $normFiles -notcontains $_ })
$sb = New-Object System.Text.StringBuilder
$selfLog = 0
foreach ($f in $corpusFiles) {
    $t = ''
    try { $t = Read-SharedText $f } catch { $readFail += $f; continue }
    # 解码不了的件不得当证据：SPLIT（写件管道坏了）与 NUL-UNDETERMINED（二进制）都只可能是“少收证据”，
    # 而“少收”只会让 R-1 更容易报红，造不出假绿。两者的**账面后果不同**：前者是缺陷要报红，后者是射程要收窄。
    if ($script:lastEncTag -eq 'SPLIT-utf8bom+utf16le' -or $script:lastEncTag -eq 'NUL-UNDETERMINED') { $encExcl++; continue }
    if (Test-CorpusSelfLog $t) { $selfLog++; continue }
    [void]$sb.Append($t)
}
foreach ($f in $tracked) {
    if (-not (Test-Path -LiteralPath $f)) { continue }
    try { [void]$sb.Append((Read-SharedText $f)) }
    catch { $readFail += $f }
}
$corpus = $sb.ToString()
# 自指碰撞闸门：corpus 里不许出现本件的源码（出现 = 判据被自己的样本喂成恒真）。
if ($corpus.Contains('synFake') -or $corpus.Contains($script:FakeIso)) { $fails += '<<< TS-CORPUS-COLLECTS-THE-CHECKER (the tool can read its own source: every fake token becomes "provable")' }
Say ('=== ts-provability @ base ' + $BaseRef + ' ===')
Say ('corpus: scratch-dir-files=' + $corpusFiles.Count + ' selflog-excluded=' + $selfLog + ' encoding-excluded=' + $encExcl + ' (SPLIT+binary) scratch-bytes=' + $corpusBytes + ' ext-histogram=[' + $extHist + '] tracked-md-files=' + $tracked.Count + ' corpus-read-failures=' + $readFail.Count + ' corpus-chars=' + $corpus.Length)
Say ('corpus-decoded-by-encoding (corpus-build only, 不含逐行引用件的回读): ' + ((($script:encHist.GetEnumerator() | Sort-Object Name) | ForEach-Object { $_.Name + '=' + $_.Value }) -join ' ') + ' (utf16le-noBOM>0 = UTF-8 grep 对它们整体不可见的那一批; SPLIT>0 = 同一件两种编码那一型)')
Say ('binary-artifacts-excluded-not-evidence (射程收窄、不报红): n=' + $script:binArt.Count + ' names=[' + (($script:binArt | Select-Object -First 3) -join ' | ') + '] (NUL 分布不定=真二进制，它们本来就不是取证件；排除只会让 R-1 更容易红，造不出假绿)')
if ($Files.Count -eq 0) { $fails += '<<< TS-NO-FACE (empty -FilesCsv turns the cell into a bypass; the face must be passed in)' }
foreach ($f in $Files) {
    if ((Invoke-Git -gargs @('ls-files', '--', $f)).Count -eq 0) { $fails += ('<<< TS-FACE-NOT-TRACKED ' + $f + ' (a face item that git cannot see judges 0 lines = a silent bypass, not a clean pass)') }
}
if ($corpusFiles.Count -eq 0 -or $corpusBytes -eq 0) { $fails += ('<<< TS-CORPUS-EMPTY (cannot read any artifact from ' + $CorpusDir + ') -- fail closed') }
if ($readFail.Count -gt 0) { $fails += ('<<< TS-CORPUS-READ-FAIL n=' + $readFail.Count + ' first=' + (($readFail | Select-Object -First 2) -join ' , ') + ' (the corpus is incomplete: a skipped source can turn a real reading into UNPROVABLE, and a dead tool turns the cell blind)') }

function Test-Tok([string]$tok) { return ($corpus.IndexOf($tok, [System.StringComparison]::Ordinal) -ge 0) }
# R-2 的“在位”判定**只有一个实现处**（下面逐行判定与 selftest-5 共用它）：写成两遍就会出现“循环里改
# 了口径、自测还在测老口径”，那一格随之变成是非器。返回 $true = 件在盘上或已入库。
function Test-Artifact([string]$name) {
    $onDisk = @(Get-ChildItem -LiteralPath $CorpusDir -File -Recurse -Filter $name -ErrorAction SilentlyContinue).Count
    $inGit = (Invoke-Git -gargs @('ls-files', '--', $name)).Count
    return (($onDisk -gt 0) -or ($inGit -gt 0))
}

# ---- R-6（刀㊶ 第四件在册义务；判据形状由 §41.3 第 11 条 + §41.8 末条预先定好，本轮从文字变机制）：
#      账面写「KEY=VALUE（件 X）」时，X 里必须真能取到那条 KEY= ⇒ 取不到报 KEY-NOT-IN-CITED-ARTIFACT。
#      防的那一型本批被照出**两次**（第一次靠 git grep 自查，第二次靠引用前先开件核），所以它不再靠自律。
#      射程：一行**恰好一个**「件 <NAME>」引用 + 该行有 KEY= 读数 ⇒ 判。
#      盲区（当场声明，不装作已防）：
#        ① 同一行多个件名 ⇒ 归属不明，跳过并计数 key-cite-multi-name-lines=（工单件那种超长单行全在这一型里）；
#        ② 「数无件名」的行只计数不判（key-no-cite-readings=），否则会把普通叙述当引用；
#        ③ KEY 一级判「键在不在」；VALUE 一级另计（key-value-checked / key-value-MISMATCH），
#          本轮先把两级都量出来，再决定 VALUE 一级能不能当绑定判据（不拿未反证的判据绑红）；
#        ④ 跳行引用（「逐字读数在 §X 行 Y」）不在射程。
# 抽取器（$CITE/$BSPAN/$BARE/$PHRASE + Get-LineKeyPairs）住单独一个 lib，本件与透视件 dot-source 同一份。
# 为什么不留在这里：“同一判据两处各写一遍”那一型在册已登多次（见 Test-Artifact 注记）；而本批新增的
# k46-r6-diag.ps1 要看的正是抽取器吐了什么，拿自己拷一份去照就照不到真行为。
. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'k46-keypair-lib.ps1')
$artCache = @{}
# 件文本只一个实现处（逐行判定与 selftest-9 共用）；写成两遍就会出现“循环里改了口径、自测还在测老口径”。
function Get-ArtifactText([string]$name) {
    if ($artCache.ContainsKey($name)) { return $artCache[$name] }
    $t = $null
    $hit = @(Get-ChildItem -LiteralPath $CorpusDir -File -Recurse -Filter $name -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($hit.Count -ge 1) {
        try { if ((Get-Item -LiteralPath $hit[0].FullName).Length -le 5MB) { $t = Read-SharedText $hit[0].FullName } } catch { $t = $null }
    } else {
        $inGit = @(Invoke-Git -gargs @('ls-files', '--', $name))
        if ($inGit.Count -gt 0 -and (Test-Path -LiteralPath $name)) {
            try { $t = Read-SharedText $name } catch { $t = $null }
        }
    }
    $artCache[$name] = $t
    # 引用面上的编码分裂单独报红： corpus 普查里“某个未引用的件坏了”只该是条计数（否则 1200 件的 scratch 面会永久红，
    # 而永久红的格跟没有格同形）；但**账面引它**时，“件在、数不在”就是当场风险，必须红。
    if ($null -ne $t -and $script:lastEncTag -eq 'SPLIT-utf8bom+utf16le') { $script:citedSplit += $name }
    return $t
}
# 取键形状（token/phrase/bare）与抽取都在 lib；本件不再自己定一份 Get-LineKeyPairs（上一版两处各写一遍时，
# 这一份把 `, @()` 那一型带进了主路径，件 k46-r6-diag-20261104-161041.txt 把它照出来了：见 lib 顶部注记）。
# 从一行里抽 KEY 读数（键可以是单个 token，也可以是短语）。
# ⚠ loose（仅末词命中）这一条本批被 selftest-9a 抬出来过：`FAKEKEY-9` 的末词是 `9`，而归一化后的件里
#   `REALKEY-9=42` 含 `9=` ⇒ 编造的键被判为“弱命中”→ 齿对 9a 永不响。现在要求末词长度 >=5 且非纯数字，
#   且 loose 仍单独计数不混进 strict（弱命中是可见数字，不是默认放过）。
function New-KeyAcc { return @{ keys = 0; strict = 0; loose = 0; keyMiss = 0; quoteMiss = 0; bareTail = 0; multi = 0; noCite = 0; absentSkip = 0; unread = 0; valChecked = 0; valMiss = 0; fail = @(); valFail = @() } }
function Add-KeyAudit {
    param($acc, [string]$text, [string]$where)
    $cites = @($CITE.Matches($text) | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique)
    $pairs = @(Get-LineKeyPairs $text)
    if ($pairs.Count -eq 0) { return }
    if ($cites.Count -eq 0) { $acc.noCite = $acc.noCite + $pairs.Count; return }
    if ($cites.Count -gt 1) { $acc.multi = $acc.multi + 1; return }
    $art = $cites[0]
    # 件不在盘：那是 R-2 的活儿（已报 ARTIFACT-NOT-ON-DISK），这里不双报也不因此静默免检
    if (-not (Test-Artifact $art)) { $acc.absentSkip = $acc.absentSkip + 1; return }
    $t = Get-ArtifactText $art
    if ($null -eq $t) { $acc.unread = $acc.unread + 1; $acc.fail += ('<<< KEY-CHECK-ARTIFACT-UNREADABLE ' + $where + ' ' + $art + ' (件在盘但读不到/超限：键这一级无法核，不得当作已过)'); return }
    $norm = $t -replace '\s*=\s*', '='
    # 逐字引用比对用“空白折叠”后的文本：件里一个数常带尾部对齐空格，而账面转述不会带着那些空格。
    $tWs = ($t -replace '[ \t]+', ' ')
    $tWsNorm = ($tWs -replace '\s*=\s*', '=')
    foreach ($pr in $pairs) {
        # ⚠ $pr 必须是 hashtable。本批实踩的形变：若抽取器 `return ,@(...)` 而调用方又 `@(...)`，
        #   元素就成了 Object[]，`$pr.key` 变成成员枚举出的**键数组** ⇒ 拼接伪键去比对（齿磨钝，读数全不可信）。
        #   现在由 selftest-9d 当场自证形状（pairs 数量与元素类型），不靠人看出“这个键怎么长这样”。
        $k = [string]$pr.key
        $form = [string]$pr.form
        if ($k -eq '') { continue }                      # 空键 = 抽取器输出坏了（本批曾靠它报出一枚假红），不得参判
        if ($form -eq 'bare-phrase-tail') { $acc.bareTail = $acc.bareTail + 1; continue }   # 短语尾巴：不判、但计数（射程边界写在 lib 顶部）
        $acc.keys = $acc.keys + 1
        if ($form -eq 'phrase') {
            # 短语形式 = 把件里的原行转述到账面。它该判“整串在不在”，而不是“短语键在不在”——
            # 后者会咬到“登记错误书写形式的那句自身文字”（本批 §41.8 末条就是这种句子）。
            $span = [string]$pr.span
            $spanNorm = ($span -replace '\s*=\s*', '=')
            if ($tWs.Contains($span) -or $tWsNorm.Contains($spanNorm)) { $acc.strict = $acc.strict + 1; continue }
            $acc.quoteMiss = $acc.quoteMiss + 1
            $acc.fail += ('<<< QUOTE-NOT-VERBATIM-IN-CITED-ARTIFACT ' + $where + ' span="' + $span + '" cited=' + $art + ' (件里没有这一整串：要么数是手拄的，要么转述时被改写过形状)')
            continue
        }
        $hit = ($t.Contains($k + '=') -or $norm.Contains($k + '='))
        if (-not $hit) {
            $last = ((($k -split '[ \-]+') | Where-Object { $_ -ne '' }) | Select-Object -Last 1)
            if ($last -and $last -ne $k -and $last.Length -ge 5 -and $last -notmatch '^\d+$' -and ($t.Contains($last + '=') -or $norm.Contains($last + '='))) { $acc.loose = $acc.loose + 1; $hit = $true }
        }
        if ($hit) { $acc.strict = $acc.strict + 1 } else {
            $acc.keyMiss = $acc.keyMiss + 1
            $acc.fail += ('<<< KEY-NOT-IN-CITED-ARTIFACT ' + $where + ' key="' + $k + '" form=' + $form + ' cited=' + $art + ' (件在盘，但件里从没打印过这个键：数绑的是件名不是内容)')
            continue
        }
        $v = [string]$pr.value
        if ($v -ne '') {
            $acc.valChecked = $acc.valChecked + 1
            if (-not ($t.Contains($k + '=' + $v) -or $norm.Contains($k + '=' + $v) -or ($t.Contains($v) -and $v.Length -ge 8))) {
                $acc.valMiss = $acc.valMiss + 1
                $acc.valFail += ('KEY-VALUE-MISMATCH ' + $where + ' "' + $k + '=' + $v + '" cited=' + $art)
            }
        }
    }
}

# ---- 取新增行（带新文件行号：从 -U0 的 hunk 头 +c,d 起算，'+' 行逐条占号）
$tokTotal = 0; $tokProv = 0; $tokUnprov = 0; $nameRefs = 0; $nameMiss = 0; $addedTotal = 0
$keyAcc = New-KeyAcc
foreach ($f in $Files) {
    $diff = Invoke-Git -gargs @('diff', '-U0', $BaseRef, '--', $f)
    $cur = 0
    foreach ($ln in $diff) {
        if ($ln -match '^@@ -\d+(?:,\d+)? \+(\d+)') { $cur = [int]$Matches[1]; continue }
        if ($ln -match '^\+\+\+' -or $ln -match '^---' -or $ln -match '^ ') { continue }
        if ($ln -match '^-') { continue }
        if (-not $ln.StartsWith('+')) { continue }
        $text = $ln.Substring(1)
        $addedTotal++
        foreach ($m in @($ISO.Matches($text) | ForEach-Object { $_.Value } | Sort-Object -Unique)) {
            $tokTotal++
            if (Test-Tok $m) { $tokProv++ }
            else { $tokUnprov++; $fails += ('<<< UNPROVABLE-TS ' + $f + ':' + $cur + ' ' + $m + ' (no artifact in the corpus contains this ISO timestamp)') }
        }
        foreach ($m in @($NAME.Matches($text) | ForEach-Object { $_.Value } | Sort-Object -Unique)) {
            $nameRefs++
            if (-not (Test-Artifact $m)) { $nameMiss++; $fails += ('<<< ARTIFACT-NOT-ON-DISK ' + $f + ':' + $cur + ' ' + $m + ' (referenced by name, exists nowhere)') }
        }
        # R-6：同一个「件 X」引用里的 KEY 读数必须真能在 X 里读到（只在这一个实现处算，自测走的也是它）
        Add-KeyAudit $keyAcc $text ($f + ':' + $cur)
        $cur++
    }
}

if ($script:gitFail.Count -gt 0) { $fails += ('<<< TS-GIT-CMD-FAIL n=' + $script:gitFail.Count + ' [' + (($script:gitFail | Select-Object -First 3) -join ' | ') + '] (git itself failed this run: an empty diff read here is NOT "no added lines", it is a blind cell)') }
foreach ($x in $keyAcc.fail) { $fails += $x }
# 编码分裂的件不得拿当证据：它的数在盘上但标面上读不到（本轮实踩，成因在上面的编码面注记）
# 被引用的件编码分裂 ⇒ 报红；盘上其他分裂件只报计数（它们是“射程内待修的历史件”，不是本刀的账面缺陷）。
Say ('encoding-split-on-disk (corpus wide, count only): n=' + $script:splitArt.Count + ' names=[' + (($script:splitArt | Select-Object -First 4) -join ' | ') + ']')
if ($script:citedSplit.Count -gt 0) { $fails += ('<<< TS-CITED-ARTIFACT-ENCODING-SPLIT n=' + $script:citedSplit.Count + ' [' + ($script:citedSplit -join ' | ') + '] (账面引了它，而它的 BOM 声明与实际解码不一致：那个数在人眼里在、在判据里不在)') }

# ---- 自测（每次都跑，与刀次无关）：新判据必须自证能咬，否则"加了格"只是口号。
# ⚠ 形状：每枚齿的“过/不过”**只在这里算一次**，打印 / 判决 / 汇总三处都读同一个数。首版是三处各写一遍条件
#   （inline `$(if)` + `$fails +=` + 门件猜行尾末词），门件因此把 selftest-4 的句尾 `note)` 当成了判决。
$synFake = $script:FakeIso
$s1 = Test-Tok $synFake
$corpusIso = @($ISO.Matches($corpus) | ForEach-Object { $_.Value })
$s2tok = if ($corpusIso.Count -ge 1) { $corpusIso[0] } else { '' }
$s2 = ($s2tok -ne '') -and (Test-Tok $s2tok)
$s3toks = @($ISO.Matches('mtime = 2026-11-04 10:46:47.723600056 +0800 以及差值 14 h 39 m'))
# R-2 也必须自证能咬：一个**必定不存在**的件名须被判为“不在位”。缺这枚自测时，若 -Filter 哪天不匹配
# （与上面①同一族：参数形状变了但调用点没变），本格会静默变成“任何件名都说在位”。
$s5 = Test-Artifact 'k9999-ts-selftest-absent.txt'
# selftest-6：让 git **真的失败一次**（rc!=0 且真往 stderr 写文本），它必须「不杀工具 + 被计数」。
#   缺这枚的后果本批实取过：工具死在 git 的 CRLF advice 上，rc=1 而 artifact 里一句判决都没有，
#   门件只能报“工具红了”而说不出为什么 —— 那一格从“判内容”退化成“判工具活着没”。
#   上面 TS-GIT-CMD-FAIL 已经先算过，所以这里的合成项不污染判决；算完再把它从计数里撤掉。
$gf0 = $script:gitFail.Count
$s6threw = $false
try { [void](Invoke-Git -gargs @('rev-parse', '--verify', 'k9999-ts-selftest-no-such-ref')) } catch { $s6threw = $true }
$s6counted = ($script:gitFail.Count -gt $gf0)
if ($s6counted) { $script:gitFail.RemoveRange($gf0, $script:gitFail.Count - $gf0) }
# selftest-7：内容闸门必须**双向**自证。它是“少收证据”那一侧的改动，不测就等于“一个谁也没看的
# 过滤条件”；而单向测又不分真假（写反了会两个方向都“过”）。形状：同一个探针文件先写成普通取件内容
# （必须入选），再写成带判决标记的内容（必须被排除），用的就是读循环那个谓词（Test-CorpusSelfLog）——
# 不是另写一遍条件。探针是本函数刚建的合成件，用完即删（它不在枚举集里，但不得留在盘上喂下一轮）。
# ⚠ 两个期望值必须写成 **True/True**（kept 与 excluded 都是“应发生”）：初版从上一个形状（mtime）抄过来时
#    保留了 `-not $s7skip`，而那个变量在新口径下叫“被排除了”，语义翻了 ⇒ 本格当场报红而不是静默过。
#    那枚红是自测框架拦住了把判据写反的我，不是工具坏了——变量名从此叫 $s7bit（咬住了）而非 $s7skip。
$probe = Join-Path (Resolve-Path $CorpusDir).Path 'k9999-ts-selftest-selflog.txt'
$s7keep = $false; $s7bit = $false; $s7err = ''
try {
    [System.IO.File]::WriteAllText($probe, ('plain artifact body, looks like a real reading ' + ('2026-01-01' + 'T00:00:00')))
    $s7keep = (-not (Test-CorpusSelfLog (Read-SharedText $probe)))
    [System.IO.File]::WriteAllText($probe, ('<<< UNPROVABLE-TS readings.md:1 ' + ('2031-12-25' + 'T06:30:00') + "`r`nTS_RC=1`r`n"))
    $s7bit = Test-CorpusSelfLog (Read-SharedText $probe)
} catch {
    $s7err = $_.Exception.Message
}
if (Test-Path -LiteralPath $probe) { Remove-Item -LiteralPath $probe -Force }
# selftest-8：**解码必须双向自证**。只测「UTF-16 能读到」这一侧写反了也不会红（把两种解码都返同一个串就过了）。
#   形状：探针 A = **无 BOM 的纯 UTF-16LE** 内容（就是普查里那 150 件的形状）⇒ 件内针必须能读到，
#   而同一个字节串按 UTF-8 解必须**读不到**（不满足后一半 = 探针是恒真的，本格就白测）。
#   探针 B = UTF-8 内容 ⇒ 照常读到（防止新逻辑把普通件也判成垃圾）。走的就是件读取那个函数（Resolve-BytesToText），不是另写一遍。
$probeU16 = Join-Path (Resolve-Path $CorpusDir).Path ($script:K99 + 'u16.txt')
$probeU8 = Join-Path (Resolve-Path $CorpusDir).Path ($script:K99 + 'u8.txt')
$s8u16 = $false; $s8naive = $true; $s8u8 = $false; $s8err8 = ''
try {
    [System.IO.File]::WriteAllBytes($probeU16, [System.Text.Encoding]::Unicode.GetBytes('UTF16NEEDLE-8=42 plain-ascii-lookalike'))
    $b8 = [System.IO.File]::ReadAllBytes($probeU16)
    $s8u16 = (Resolve-BytesToText $b8).text.Contains('UTF16NEEDLE-8=')
    $s8naive = ([System.Text.Encoding]::UTF8.GetString($b8)).Contains('UTF16NEEDLE-8=')
    [System.IO.File]::WriteAllBytes($probeU8, [System.Text.Encoding]::UTF8.GetBytes('UTF8NEEDLE-8=43'))
    $s8u8 = (Resolve-BytesToText ([System.IO.File]::ReadAllBytes($probeU8))).text.Contains('UTF8NEEDLE-8=')
} catch { $s8err8 = $_.Exception.Message }
foreach ($pp in @($probeU16, $probeU8)) { if (Test-Path -LiteralPath $pp) { Remove-Item -LiteralPath $pp -Force } }
# selftest-9：R-6 必须**双向**自证（同一实现处 Add-KeyAudit），并自证**抽取器输出形状**（9d）。
#   9a 咬：账面写一个探针件里根本没打印过的键 ⇒ keyMiss 必须 =1（=0 即这枚齿永不响，与 mtime 那一型同族）。
#   9b 过：账面写的键在件里是以**带空格的 `KEY = VALUE`** 形式存在的 ⇒ 必须判为“键在 + 值对”（不能因书写空格就假红）。
#   9c 不恒真：拿一个不存在的件名跑同一把函数 ⇒ 不得判成命中（走 absentSkip，不产 <<<）。
#   9d 形状：一行三个读数必须抽出**三个 hashtable**（不是“1 个 Object[] 元素”）。本批实踩的正是它：
#     抽取器写 `return ,@(...)`、调用方又套 `@(...)` ⇒ 多一层嵌套 ⇒ `$pr.key` 成为成员枚举出的键数组
#     ⇒ 拼接伪键去比对 ⇒ R-6 对任何账面只能产出垃圾判决（件 k46-r6-diag-20261104-161041.txt 逐字读到
#     `extracted-pairs=1 / elem-type=Object[] / key-array-count=3`）。没有这枚自测，同一型会再长回来。
$probeK9 = Join-Path (Resolve-Path $CorpusDir).Path ($script:K99 + 'key.txt')
$s9bite = $false; $s9hit = $false; $s9val = $false; $s9skip = $false; $s9shape = $false; $s9err9 = ''; $s9num = ''
try {
    [System.IO.File]::WriteAllText($probeK9, "REALKEY-9 = 42`r`nsecond line`r`n")
    $artCache.Clear()
    $a9x = New-KeyAcc
    Add-KeyAudit $a9x ('这一行把数绑到件上：`FAKEKEY-9=7`（件 ' + $script:K99 + 'key.txt）') 'selftest-9a'
    # ⚠ 期望必须带 `<<< ` 前缀：那是“红线”的契约形状（门件按 `<<<` 数红行、内容闸门按行首 `<<< ` 认判决行）。
    #   本批首版写成 `-like 'KEY-NOT-IN-CITED-ARTIFACT*'` ⇒ 齿真咬到了、自测却说没咬到（假红）：那是自测
    #   被抓住（把期望写反），不是工具坏。形状从此跟契约走，不跟文案走。
    $s9bite = (($a9x.keyMiss -eq 1) -and ($a9x.fail.Count -ge 1) -and ($a9x.fail[0] -like '<<< KEY-NOT-IN-CITED-ARTIFACT*'))
    $a9y = New-KeyAcc
    Add-KeyAudit $a9y ('这一行键对值也对：`REALKEY-9=42`（件 ' + $script:K99 + 'key.txt）') 'selftest-9b'
    $s9hit = (($a9y.keys -ge 1) -and ($a9y.keyMiss -eq 0) -and ($a9y.fail.Count -eq 0))
    $s9val = (($a9y.valChecked -ge 1) -and ($a9y.valMiss -eq 0))
    $a9z = New-KeyAcc
    Add-KeyAudit $a9z ('这一行引用的件不存在：`SOMEKEY-9=1`（件 ' + $script:K98 + 'absent.txt）') 'selftest-9c'
    $s9skip = (($a9z.absentSkip -eq 1) -and ($a9z.keys -eq 0) -and ($a9z.fail.Count -eq 0))
    $p9d = @(Get-LineKeyPairs '三个读数：`alpha-9=1`、`beta-9=2` 以及 gamma-9=3 尾巴')
    $h9d = @($p9d | Where-Object { $_ -is [hashtable] }).Count
    $s9shape = (($p9d.Count -eq 3) -and ($h9d -eq 3))
    # 把中间量当**读数**打印（不只报布尔）：否则下一轮又得靠重写一遍诊断才能知道是哪一环翻了。
    $s9num = ('9a-keyMiss=' + $a9x.keyMiss + ' 9b-keys=' + $a9y.keys + ' 9b-valChecked=' + $a9y.valChecked + ' 9c-absentSkip=' + $a9z.absentSkip + ' 9d-pairs=' + $p9d.Count + ' hashTables=' + $h9d)
} catch { $s9err9 = $_.Exception.Message }
if (Test-Path -LiteralPath $probeK9) { Remove-Item -LiteralPath $probeK9 -Force }
# selftest-10：短语形式（逐字引用）的齿也必须双向自证。
#   10a 咬：账面转述时把件里原行改了形（`QUOTEWORD-10 other run = 9` vs 件里 `--- QUOTEWORD-10 this run = 7 ---`）
#        ⇒ 必产 QUOTE-NOT-VERBATIM，且**不得同时产 KEY-NOT-IN-CITED**（同一读数只允许一枚判决，不然双报会让人以为有两个缺陷）。
#   10b 过：逐字串（只在两端多几个破折号、空格个数不同）⇒ 不得报红。防的是“齿咬到把自己的缺陷登记在案的那句自身文字”
#        （本批 §41.8 末条止就是那种句子：它引用错误形式是为了说明它错）。
$probeQ10 = Join-Path (Resolve-Path $CorpusDir).Path ($script:K99 + 'quote.txt')
$s10bite = $false; $s10pass = $false; $s10err10 = ''; $s10num = ''
try {
    [System.IO.File]::WriteAllText($probeQ10, "header`r`n--- QUOTEWORD-10 this run = 7 ---`r`n")
    $artCache.Clear()
    $a10x = New-KeyAcc
    Add-KeyAudit $a10x ('这一行转述过形：`QUOTEWORD-10 other run = 9`（件 ' + $script:K99 + 'quote.txt）') 'selftest-10a'
    $s10bite = (($a10x.quoteMiss -eq 1) -and ($a10x.keyMiss -eq 0) -and ($a10x.fail.Count -ge 1) -and ($a10x.fail[0] -like '<<< QUOTE-NOT-VERBATIM-IN-CITED-ARTIFACT*'))
    $a10y = New-KeyAcc
    Add-KeyAudit $a10y ('这一行是逐字串：`QUOTEWORD-10 this run = 7`（件 ' + $script:K99 + 'quote.txt）') 'selftest-10b'
    $s10pass = (($a10y.strict -ge 1) -and ($a10y.quoteMiss -eq 0) -and ($a10y.fail.Count -eq 0))
    $s10num = ('10a-quoteMiss=' + $a10x.quoteMiss + ' keyMiss=' + $a10x.keyMiss + ' 10b-strict=' + $a10y.strict + ' quoteMiss=' + $a10y.quoteMiss)
} catch { $s10err10 = $_.Exception.Message }
if (Test-Path -LiteralPath $probeQ10) { Remove-Item -LiteralPath $probeQ10 -Force }
$artCache.Clear()
$st = @(
    @{ id = '1'; name = 'FAKE-BITES'; ok = (-not $s1); txt = ('fake ISO vs real corpus => provable=' + $s1 + ' (expect False; True would mean the comparator always passes)'); fail = 'the R-1 comparator is a yes-man: every fabricated timestamp would read as provable' },
    @{ id = '2'; name = 'REAL-PASSES'; ok = $s2; txt = ('token harvested from corpus => provable=' + $s2 + ' (expect True; the sample is ' + $s2tok + ')'); fail = 'the corpus is not being read as text' },
    @{ id = '3'; name = 'FORMAT-BOUNDARY-OK'; ok = ($s3toks.Count -eq 0); txt = ('space-form timestamp must NOT be scanned => extracted=' + $s3toks.Count + ' (expect 0; over-biting would force the ledger to hide readings)'); fail = 'the cell bites non-ISO forms too: honest space-form readings would be punished' },
    @{ id = '5'; name = 'ABSENT-BITES'; ok = (-not $s5); txt = ('synthetic absent artifact name => on-disk=' + $s5 + ' (expect False; True means the artifact comparator is a yes-man)'); fail = 'ARTIFACT-NOT-ON-DISK can never fire' },
    @{ id = '4'; name = 'NON-EMPTY-OK'; ok = (($corpusFiles.Count -gt 0) -and ($corpusBytes -gt 0)); txt = ('corpus guard: this run read files=' + $corpusFiles.Count + ' bytes=' + $corpusBytes + ' (empty => TS-CORPUS-EMPTY must fail closed)'); fail = 'see TS-CORPUS-EMPTY' },
    @{ id = '6'; name = 'GIT-STDERR-NO-KILL'; ok = ((-not $s6threw) -and $s6counted); txt = ('real git failure (stderr text + rc!=0) => threw=' + $s6threw + ' counted=' + $s6counted + ' (expect False/True: stderr must not kill the tool, rc must not be swallowed)'); fail = 'the tool dies on native stderr, or a git failure reads as an empty diff = a blind cell reporting "clean"' },
    @{ id = '7'; name = 'SELFLOG-EXCLUDE-BOTH-WAYS'; ok = ($s7keep -and $s7bit); txt = ('same probe: plain-body-kept=' + $s7keep + ' / verdict-log-excluded=' + $s7bit + ' (expect True/True' + $(if ($s7err) { '; probe error: ' + $s7err }) + ')'); fail = 'the content gate is unverified in one direction: either real artifacts get dropped, or a previous run of this checker becomes evidence and R-1 turns into a yes-man' },
    @{ id = '8'; name = 'DECODE-BOTH-WAYS'; ok = ($s8u16 -and (-not $s8naive) -and $s8u8); txt = ('BOM-less UTF-16LE probe: decoded-hit=' + $s8u16 + ' naive-utf8-hit=' + $s8naive + ' / utf8-probe-hit=' + $s8u8 + ' (expect True/False/True; True/True means the probe itself is vacuous)' + $(if ($s8err8) { '; probe error: ' + $s8err8 }) + ')'); fail = 'the reader does not match the writer: UTF-16 artifacts stay invisible, so a real number reads as MISSING and the self-log content gate never fires on them' },
    @{ id = '9'; name = 'KEY-IN-CITED-ARTIFACT-BOTH-WAYS'; ok = ($s9bite -and $s9hit -and $s9val -and $s9skip -and $s9shape); txt = ('probe artifact: fabricated-key-bites=' + $s9bite + ' / spaced-form-passes=' + $s9hit + ' value-checked=' + $s9val + ' / absent-artifact-skipped=' + $s9skip + ' / extractor-shape-ok=' + $s9shape + ' (expect True x5; ' + $s9num + $(if ($s9err9) { '; probe error: ' + $s9err9 }) + ')'); fail = 'R-6 either never fires (the 绑件不绑数 型 stays unpunished), fires on formatting noise (the ledger starts hiding readings), or judges on a nested/pseudo key (the tooth is blunt and its TALLY is fiction)' },
    @{ id = '10'; name = 'QUOTE-VERBATIM-BOTH-WAYS'; ok = ($s10bite -and $s10pass); txt = ('phrase-form reading vs cited artifact: rewritten-bites=' + $s10bite + ' / verbatim-passes=' + $s10pass + ' (expect True/True; ' + $s10num + $(if ($s10err10) { '; probe error: ' + $s10err10 }) + ')'); fail = 'the 转述过形那一型无人管（账面可以把件里的原行改写后自称逐字），或者它咬到“登记错误形式”的自身文字' }
)
foreach ($x in $st) { Say ('ts-selftest-' + $x.id + ') ' + $x.txt + ' ' + $(if ($x.ok) { $x.name } else { '<<< TS-SELFTEST-' + $x.id + '-FAILED' })) }
$stBad = @($st | Where-Object { -not $_.ok })
Say ('ts-selftests) n=' + $st.Count + ' passed=' + (($st.Count) - $stBad.Count) + ' names=[' + (($st | ForEach-Object { $_.name }) -join ' ') + ']')
if ($stBad.Count -gt 0) { $fails += ('<<< TS-SELFTESTS-FAILED n=' + $stBad.Count + ' [' + (($stBad | ForEach-Object { $_.id + ':' + $_.fail }) -join ' | ') + ']') }
# 零新增行 = 这一格什么都没看（新文件未进 index 时 git diff 不列它，历史已踩过这一型）。
# 本格不自己判红（红不红由门件绑），但必须把数报出来，否则“看过”与“没看过”同形。
Say ('ts-witness) added-lines-total=' + $addedTotal + ' (the gate binds this to > 0; 0 here means the cell is vacuous this round)')

Say ('TALLY iso-tokens-scanned=' + $tokTotal + ' provable=' + $tokProv + ' UNPROVABLE=' + $tokUnprov + ' | artifact-refs=' + $nameRefs + ' missing=' + $nameMiss + ' | face-files=' + $Files.Count + ' | added-lines-total=' + $addedTotal)
Say ('R-6 TALLY keys=' + $keyAcc.keys + ' strict=' + $keyAcc.strict + ' loose=' + $keyAcc.loose + ' KEY-NOT-IN-CITED-ARTIFACT=' + $keyAcc.keyMiss + ' QUOTE-NOT-VERBATIM=' + $keyAcc.quoteMiss + ' | skipped: multi-name-lines=' + $keyAcc.multi + ' no-cite-readings=' + $keyAcc.noCite + ' bare-phrase-tails=' + $keyAcc.bareTail + ' absent-artifact=' + $keyAcc.absentSkip + ' unreadable=' + $keyAcc.unread + ' | VALUE-level(本轮只量不绑): checked=' + $keyAcc.valChecked + ' mismatch=' + $keyAcc.valMiss + $(if ($keyAcc.valMiss -gt 0) { ' first=[' + (($keyAcc.valFail | Select-Object -First 2) -join ' ] [ ') + ']' } else { '' }))
foreach ($x in $fails) { Say ('   ' + $x) }
$rc = if ($fails.Count -eq 0) { 0 } else { 1 }
Say ('TS_RC=' + $rc)
exit $rc
