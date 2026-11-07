# k71-basis.ps1 —— 面基准的**唯一调用层**（本机侧薄适配，判据住在仓内 scripts/evidence/face_basis.py）。
#
# 为什么还要这一层：仓内实现是 Python，四把本机量具（k70-attribution / k70-ext-derive /
# k70-candidate-derive / e26-gate-fill）都是 PowerShell。如果各自去 `& python ... --mode face`
# 再各自切 stdout，那就是把"散点式实现"从 git 命令挪到了字符串解析上——同一型缺陷换了载体。
# 所以这里只准有一处解析，消费方拿到的永远是同一个形状。
#
# 在册规矩（本轮新增的门禁齿 B6 就是照这条判据写的）：本机量具体内**不得**再出现
# `git diff --name-only` / `git status --porcelain` / `git ls-files --others` 这三条基准构造，
# 本文件是唯一白名单项。
#
# stderr 一律分件（在册坑：PowerShell 5.1 + ErrorActionPreference=Stop 会把 native stderr
# 包成 NativeCommandError，真 traceback 反而读不到；工具死了必须当场拒判，不许拿空 stdout 当"无违规"）。

$script:BasisImplRel = 'scripts/evidence/face_basis.py'

function Invoke-BasisImpl {
    param([string]$RepoRoot, [string[]]$ImplArgs, [string]$Tag)
    $py = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    $impl = Join-Path $RepoRoot ($script:BasisImplRel -replace '/', '\')
    if (-not (Test-Path -LiteralPath $py)) { return @{ rc = 2; lines = @(); errFile = ''; why = 'PY-ABSENT' } }
    if (-not (Test-Path -LiteralPath $impl)) { return @{ rc = 2; lines = @(); errFile = ''; why = 'IMPL-ABSENT' } }
    $errFile = Join-Path $RepoRoot (".tmp-scratch/ap-visual/k71-basis-$Tag-stderr.txt")
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $argv = @('-B', $impl) + $ImplArgs
    $txt = (& $py @argv 2> $errFile | Out-String)
    $rc = $LASTEXITCODE
    $ErrorActionPreference = $prev
    $errBytes = if (Test-Path -LiteralPath $errFile) { (Get-Item -LiteralPath $errFile).Length } else { 0 }
    if ($errBytes -gt 0 -and $rc -eq 0) {
        # rc=0 而 stderr 有字节：读数不可信（工具在"通过"的同时报了什么），交调用方拒判。
        return @{ rc = 90; lines = @(); errFile = $errFile; why = 'STDERR-WHILE-PASSING' }
    }
    return @{ rc = $rc; lines = @($txt -split "`r?`n" | Where-Object { $_ -match '\S' }); errFile = $errFile; why = '' }
}

function Get-BasisField([string[]]$lines, [string]$prefix, [string]$key) {
    $row = @($lines | Where-Object { $_ -like ($prefix + '*') })
    if ($row.Count -ne 1) { return '' }
    # 单一形状：`key=value`，value 取到下一个空白/右括号。
    # 本轮实踩两次：① 上一版写了两条分支（十六进制 / 数字），对 `head=2d5bb0ff...` 会先命中
    # 数字那条返成 `head=2` —— 解析层自己把读数截断，比不解析更坏（它看着像个值）。
    # ② 修它时把换行写成了字面 `\n`，整行以 `#` 开头 ⇒ 下面的赋值语句被吞进注释，
    #    函数变成「对任何键都静默返回空串」。空串在调用方是「没有这个字段」，
    #    而「没有」和「读成空」在这一层之后再也分不出来 —— 同型缺陷第六次。
    $m = [regex]::Match($row[0], ('(?:^|[\s(])' + [regex]::Escape($key) + '=([^\s)]+)'))
    if (-not $m.Success) { return '' }
    return $m.Groups[1].Value
}

function Get-BasisPaths([string[]]$lines, [string]$tag) {
    return @($lines | Where-Object { $_ -like ($tag + ': *') } | ForEach-Object { ($_ -split ': ', 2)[1].Trim() })
}

# 面基准：face = `git diff --name-only HEAD`（仓内实现里那条唯一定义）。
function Get-BasisFace([string]$RepoRoot, [string]$Tag) {
    $r = Invoke-BasisImpl -RepoRoot $RepoRoot -ImplArgs @('--mode', 'face') -Tag $Tag
    if ($r.rc -eq 2) { return @{ ok = $false; rc = 2; why = $r.why; face = @(); offFace = @(); scatter = @(); head = '' } }
    $off = @(Get-BasisPaths $r.lines 'NEW-NOT-INTENT-ADDED')
    $sc = @(Get-BasisPaths $r.lines 'FACE-BASIS-SCATTER')
    $headRow = @($r.lines | Where-Object { $_ -like 'FACE-BASIS)*' })
    if ($headRow.Count -ne 1) { return @{ ok = $false; rc = 91; why = 'NO-VERDICT-LINE'; face = @(); offFace = @(); scatter = @(); head = '' } }
    return @{
        ok = ($r.rc -eq 0 -and $off.Count -eq 0 -and $sc.Count -eq 0)
        rc = $r.rc
        why = $(if ($off.Count) { 'NEW-NOT-INTENT-ADDED' } elseif ($sc.Count) { 'FACE-BASIS-SCATTER' } else { '' })
        face = @(Get-BasisPaths $r.lines 'FACE-PATH')
        offFace = $off
        scatter = $sc
        head = (Get-BasisField $r.lines 'FACE-BASIS)' 'head')
        counts = $headRow[0]
        lines = $r.lines
        errFile = $r.errFile
    }
}

# 申报集：从量具落盘件读（键绑内容 —— 计数键 / 路径行 / 判决当时的 HEAD 三者同源才放行）。
function Get-BasisDerived([string]$RepoRoot, [string]$File, [string]$Key, [string]$ExpectHead, [string]$Tag) {
    $argv = @('--mode', 'derived', '--file', $File, '--key', $Key)
    if ($ExpectHead) { $argv += @('--expect-head', $ExpectHead) }
    $r = Invoke-BasisImpl -RepoRoot $RepoRoot -ImplArgs $argv -Tag $Tag
    $row = @($r.lines | Where-Object { $_ -like 'DERIVED)*' })
    if ($row.Count -ne 1) { return @{ ok = $false; rc = 92; why = 'NO-DERIVED-VERDICT'; paths = @(); raw = '' } }
    $bind = ([regex]::Match($row[0], 'BIND=(\S+)')).Groups[1].Value
    return @{
        ok = ($bind -eq 'OK')
        rc = $r.rc
        why = $(if ($bind -eq 'OK') { '' } else { $bind })
        paths = @(Get-BasisPaths $r.lines ($Key + '-FILE'))
        raw = $row[0]
        lines = $r.lines
    }
}

# ext 减法的前提：这一行判决还成立不成立（内容指纹逐字相同）。
function Get-BasisExtFresh([string]$RepoRoot, [string]$ExtFile, [string]$HashFile, [string]$Tag) {
    $r = Invoke-BasisImpl -RepoRoot $RepoRoot -ImplArgs @('--mode', 'ext-fresh', '--file', $ExtFile, '--hash-file', $HashFile) -Tag $Tag
    $row = @($r.lines | Where-Object { $_ -like 'EXT-FRESH)*' })
    if ($row.Count -ne 1) { return @{ ok = $false; rc = 92; why = 'NO-EXT-FRESH-VERDICT'; raw = '' } }
    $unbound = [int]([regex]::Match($row[0], 'unbound=(\d+)').Groups[1].Value)
    return @{ ok = ($r.rc -eq 0 -and $unbound -eq 0); rc = $r.rc; why = $(if ($unbound) { "EXT-VERDICT-UNBOUND=$unbound" } else { '' }); raw = $row[0]; lines = $r.lines }
}

# 自测：拿合成样件跑**同一个**函数（在册元判据：不复刻就不测这一刀走的那段代码）。
# 返回格数与红格数；调用方必须把"格数为 0"和"红格数 > 0"都当拒判。
function Get-BasisSelfTest([string]$RepoRoot) {
    $r = Invoke-BasisImpl -RepoRoot $RepoRoot -ImplArgs @('--mode', 'selftest') -Tag 'selftest'
    $row = @($r.lines | Where-Object { $_ -like 'FACE-BASIS-SELFTEST)*' })
    $rcRow = @($r.lines | Where-Object { $_ -like 'FACE-BASIS-SELFTEST-RC=*' })
    if ($row.Count -ne 1 -or $rcRow.Count -ne 1) { return @{ ok = $false; cells = 0; failed = -1; why = 'NO-SELFTEST-VERDICT'; names = @() } }
    $pairs = @(($row[0] -replace '^FACE-BASIS-SELFTEST\)\s*', '') -split '\s+' | Where-Object { $_ -match '=' })
    $names = @($pairs | ForEach-Object { ($_ -split '=', 2)[0] })
    $bad = @($pairs | Where-Object { $_ -like '*<<<*' })
    $reported = [int](([regex]::Match($rcRow[0], 'RC=(\d+)')).Groups[1].Value)
    return @{
        ok = ($names.Count -ge 10 -and $bad.Count -eq 0 -and $reported -eq 0)
        cells = $names.Count
        failed = $bad.Count
        reportedRc = $reported
        names = $names
        why = $(if ($names.Count -lt 10) { "CELLS-UNDER-FLOOR=$($names.Count)" } elseif ($bad.Count) { "RED-CELLS=$($bad.Count)" } elseif ($reported -ne 0) { "SELF-RC=$reported" } else { '' })
    }
}
