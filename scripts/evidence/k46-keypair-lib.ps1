# k46-keypair-lib.ps1 — R-6 的「账面读数抽取」**唯一实现处**（刀㊶ 第四件期外抽出）
# 为什么单独一个文件：ts-provability.ps1 的逐行判定与 k46-r6-diag.ps1 的透视必须走同一把抽取器。
#   写成两遍就会出现「主路径改了口径、诊断还在报老口径」——那正是本仓登记过的「同一判据两处各写一遍」那一型
#   （见 ts-provability.ps1 里 Test-Artifact / Get-ArtifactText 的同源注记）。
# 本 lib **不产判决**：它只把一行账面文字拆成 (key, value, form) 三元组。咬不咬由调用方判。
# 依赖：无（纯字符串）。调用方须先 Set-Location 到仓库根？不需要。

# 「件 <NAME>」引用：一件名一行，归属才明确（同一行多个件名 ⇒ 射程外，调用方计数跳过）。
$CITE = [regex]'件\s*((?:k\d{1,3}|e\d{1,3})-[A-Za-z0-9._\-]+\.(?:txt|log|json|md|ps1|sh|csv|png|svg|bundle|log))'
$BSPAN = [regex]'`([^`]+)`'
$BARE = [regex]'([A-Za-z][A-Za-z0-9_.\-]{1,})\s*=\s*[^\s=]'
# 键短语形状：ASCII token，词间允许单个空格/连字符。冒号、括号、中文一律不算键。
$PHRASE = '^[A-Za-z0-9_.\-]+(?:[ \-]+[A-Za-z0-9_.\-]+)*$'
$TOKEN = '^[A-Za-z][A-Za-z0-9_.\-]{1,}$'

function Get-LineKeyPairs([string]$text) {
    # 返回 @{ key; value; form; span }。form 三值：
    #   token  —— 键是单个 ASCII token（`files=1`、`rc=0`）⇒ 调用方按「件里有没有这个键」判；
    #   phrase —— 键是短语且值在反引号内（`blockers collected this run = 3`）⇒ 这是**逐字引用**，
    #             调用方判「件里有没有这一整串」，不该判短语键存不存在（否则齿会咬到登记错误形式的自身文字）；
    #   bare   —— 反引号外的裸 `KEY=`（叙述里的形状，如 HEAD 之后那个）⇒ 只判键，无值。
    #   bare-phrase-tail —— 裸键前面是「ASCII 词 + 空格」⇒ 它是一句短语的尾巴（本批实踩：
    #     「blockers collected = 3」被抽成 key="collected"）。这类不得当 token 键判（否则永远是假红），
    #     但也不得静默丢：调用方计数 bareTail，让“没判”与“判了”在读数上可区分。
    #     ⚠ 尾巴判据只看 ASCII：CJK + 空格 + 键 是合法书写（“读数 nul=8463”），不能误伤。
    # ⚠ 返回**普通数组**，不要写 `return ,@(...)`：调用方一律 `@(Get-LineKeyPairs ...)` 包一层防单元素拆包，
    #   而 `,` + `@()` 会**多套一层**（调用方拿到 1 个元素、其类型是 Object[]，`$pr.key` 变成成员枚举出来的
    #   键数组 ⇒ 拼接伪键去比对）。本批实踩，件 k46-r6-diag-20261104-161041.txt 逐字读到
    #   `extracted-pairs=1 / elem-type=Object[] / key-array-count=3`——那把齿就是这么被磨钝的。
    $res = @()
    foreach ($m in $BSPAN.Matches($text)) {
        $span = $m.Groups[1].Value
        $eq = $span.IndexOf('=')
        if ($eq -le 0) { continue }
        $k = $span.Substring(0, $eq).Trim()
        $v = $span.Substring($eq + 1).Trim()
        if ($v.Contains('=')) { $v = '' }                     # 一个 span 里多个 = ⇒ 值归属不明，只判键
        # ⚠ 字符类里不能写 `\]`：那是唯一的一个 `]`，类因此永不闭合 ⇒「pattern not valid」（本批实踩）。
        $v = ($v -replace '[，、；。））】]+$', '')
        $v = ($v -replace '^[-\s]+|[-\s]+$', '')              # 逐字引用常见的 `--- xxx = 3 ---` 两端破折号
        $k = ($k -replace '^[ -]+|[ -]+$', '')
        if ($k -notmatch $PHRASE -or $k.Length -gt 60) { continue }
        $form = if ($k -match $TOKEN) { 'token' } else { 'phrase' }
        $res += @{ key = $k; value = $v; form = $form; span = ($span -replace '\s+', ' ').Trim() }
    }
    # ⚠ 局部变量不得叫 $bare：PS 变量名**大小写不敏感**，它会用字符串覆盖掉上面那个 [regex] $BARE
    #   （本批实踩：报错行就是 `$BARE.Matches` 变成 `String.Matches`）。
    $noSpan = $BSPAN.Replace($text, ' ')
    foreach ($m in $BARE.Matches($noSpan)) {
        $bf = 'bare'
        $i = $m.Groups[1].Index
        if ($i -ge 2 -and $noSpan[$i - 1] -eq ' ' -and $noSpan[$i - 2] -match '[A-Za-z0-9]') { $bf = 'bare-phrase-tail' }
        $res += @{ key = $m.Groups[1].Value; value = ''; form = $bf; span = [string]$m.Groups[1].Value }
    }
    return @($res | ForEach-Object { ('{0}|{1}|{2}|{3}' -f $_.key, $_.value, $_.form, $_.span) } | Sort-Object -Unique | ForEach-Object {
            $a = $_ -split '\|', 4
            @{ key = $a[0]; value = $(if ($a.Count -ge 2) { $a[1] } else { '' });
               form = $(if ($a.Count -ge 3) { $a[2] } else { 'token' });
               span = $(if ($a.Count -ge 4) { $a[3] } else { $a[0] }) } })
}
