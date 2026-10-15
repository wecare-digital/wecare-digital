<#
    Email authentication preflight for wecare.digital

    Verifies SPF / DKIM / DMARC / MTA-STS / TLS-RPT and, most importantly, that
    the MTA-STS policy's mx: lines still match the live MX records.

    MUST be run BEFORE any MX change (leaving Google Workspace, inserting a
    filtering gateway) and AFTER any change to the MTA-STS policy.

    Read-only: DNS queries plus one HTTPS GET. Touches no AWS resources.

    NOTE: deliberately ASCII-only. Windows PowerShell 5.1 decodes .ps1 as ANSI
    when there is no BOM, so non-ASCII characters here would corrupt parsing.

    Usage:
        powershell -File scripts/verify-email-auth.ps1
        powershell -File scripts/verify-email-auth.ps1 -Domain wecare.digital

    Deliberately NOT named _verify_*.ps1: .gitignore treats the underscore
    prefix as "utility scripts (local only)", and this one must be committed
    because .kiro/steering/email-auth-dns.md instructs people to run it.
#>

[CmdletBinding()]
param(
    [string]$Domain   = 'wecare.digital',
    [string]$Resolver = '8.8.8.8'
)

$script:Failures = 0
$script:Warnings = 0

function Pass ($m) { Write-Host "  [PASS] $m" -ForegroundColor Green }
function Fail ($m) { Write-Host "  [FAIL] $m" -ForegroundColor Red;    $script:Failures++ }
function Warn ($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow; $script:Warnings++ }
function Head ($m) { Write-Host ''; Write-Host $m -ForegroundColor Cyan }

function Get-Txt ($name) {
    try {
        Resolve-DnsName -Name $name -Type TXT -Server $Resolver -ErrorAction Stop |
            Where-Object { $_.Strings } |
            ForEach-Object { $_.Strings -join '' }
    } catch { @() }
}

$seenIncludes = @{}
function Measure-SpfLookups ($record, $depth) {
    if ($depth -gt 5) { return 0 }
    $n = 0
    foreach ($m in [regex]::Matches($record, '(?:include:|redirect=)([^\s]+)')) {
        $target = $m.Groups[1].Value
        $n++
        if (-not $seenIncludes.ContainsKey($target)) {
            $seenIncludes[$target] = $true
            $child = @(Get-Txt $target | Where-Object { $_ -match '^v=spf1' })
            if ($child.Count -ge 1) { $n += Measure-SpfLookups $child[0] ($depth + 1) }
        }
    }
    $n += ([regex]::Matches($record, '(?:^|\s)(?:a|mx|exists|ptr)[:\s]')).Count
    return $n
}

# ------------------------------------------------------------------- MX ------
Head 'MX records'
$mx = @()
try {
    $mx = @(Resolve-DnsName -Name $Domain -Type MX -Server $Resolver -ErrorAction Stop |
                Where-Object { $_.NameExchange } | Sort-Object Preference)
} catch { }

if ($mx.Count -eq 0) {
    Fail 'no MX records resolved'
} else {
    foreach ($r in $mx) { Pass "$($r.NameExchange) (pref $($r.Preference))" }
}
$liveMx = @($mx | ForEach-Object { $_.NameExchange })

# ------------------------------------------------------------------ SPF ------
Head 'SPF'
$spf = @(Get-Txt $Domain | Where-Object { $_ -match '^v=spf1' })

if ($spf.Count -eq 0) {
    Fail 'no SPF record'
} elseif ($spf.Count -gt 1) {
    Fail "$($spf.Count) SPF records - RFC 7208 permerror, must be exactly 1"
} else {
    Pass $spf[0]
    $lookups = Measure-SpfLookups $spf[0] 0
    if ($lookups -gt 10) {
        Fail "$lookups DNS lookups - exceeds RFC 7208 limit of 10, SPF will permerror"
    } elseif ($lookups -ge 8) {
        Warn "$lookups of 10 DNS lookups used - little headroom for another sender"
    } else {
        Pass "$lookups of 10 DNS lookups used"
    }
    if ($spf[0] -notmatch '[-~]all') { Warn 'no -all or ~all terminator' }
}

# ----------------------------------------------------------------- DKIM ------
# Grouped per sending service. A service is healthy if it has at least one
# resolvable key, because a signer only uses one selector per message. SES Easy
# DKIM in particular publishes 3 tokens but signs with a single one, so partial
# resolution is normal and must not be reported as a failure.
Head 'DKIM by sending service'

$dkimGroups = @(
    @{ Name = 'Google Workspace';      NeedAll = $true;  Selectors = @('google') }
    @{ Name = 'Amazon SES';            NeedAll = $false; Selectors = @(
            'v5w4wexbfyum54omlfe7l6ayada7j2nq',
            'cv4zuam4avmurrtes4etpikvkkbkxect',
            'mopqbzjxtouvnrv23lnfspfxxt2kiqpa') }
)

foreach ($g in $dkimGroups) {
    $ok = @(); $bad = @()
    foreach ($sel in $g.Selectors) {
        $val = (@(Get-Txt "$sel._domainkey.$Domain")) -join ''
        if ($val -match 'p=[A-Za-z0-9+/]{40,}') { $ok += $sel } else { $bad += $sel }
    }

    $label = $g.Name
    if ($ok.Count -eq $g.Selectors.Count) {
        Pass "$label : all $($ok.Count) selector(s) resolve"
    } elseif ($ok.Count -eq 0) {
        Fail "$label : NO selector resolves - this sender cannot pass DMARC on DKIM"
    } elseif ($g.NeedAll) {
        Fail "$label : only $($ok.Count)/$($g.Selectors.Count) resolve - missing: $($bad -join ', ')"
    } else {
        Pass "$label : $($ok.Count)/$($g.Selectors.Count) resolve, signing key available ($($ok[0].Substring(0,12))..)"
        Warn "$label : $($bad.Count) token(s) have no key published by AWS at *.dkim.amazonses.com"
        Warn "$label : confirm the s= selector on a real sent message matches a resolving token"
    }
}

# ---------------------------------------------------------------- DMARC ------
Head 'DMARC'
$dmarc = @(Get-Txt "_dmarc.$Domain" | Where-Object { $_ -match 'v=DMARC1' })

if ($dmarc.Count -eq 0) {
    Fail 'no DMARC record'
} elseif ($dmarc.Count -gt 1) {
    Fail "$($dmarc.Count) DMARC records - RFC 7489 6.6.3 treats this as NO policy at all"
} else {
    $d = $dmarc[0]
    Pass $d
    if     ($d -match 'p=reject')     { Pass 'p=reject - unaligned mail is bounced, not quarantined' }
    elseif ($d -match 'p=quarantine') { Warn 'p=quarantine - not yet at reject' }
    else                              { Warn 'p=none - monitoring only, no enforcement' }

    if ($d -match 'aspf=s') { Warn 'aspf=s - requires the envelope domain to equal From on every sender' }
    else                    { Pass 'aspf relaxed' }
    if ($d -match 'adkim=s') { Warn 'adkim=s - requires exact d= match on every sender' }
    else                     { Pass 'adkim relaxed' }

    if ($d -notmatch 'rua=') { Fail 'no rua= - enforcing with no aggregate report telemetry' }
    else                     { Pass 'rua present' }
}

# -------------------------------------------------------------- MTA-STS ------
Head 'MTA-STS'
$sts = @(Get-Txt "_mta-sts.$Domain" | Where-Object { $_ -match 'v=STSv1' })

if ($sts.Count -eq 0)     { Fail 'no _mta-sts TXT record' }
elseif ($sts.Count -gt 1) { Fail "$($sts.Count) _mta-sts records - must be exactly 1" }
else                      { Pass $sts[0] }

$policy = $null
try {
    $resp = Invoke-WebRequest -Uri "https://mta-sts.$Domain/.well-known/mta-sts.txt" `
                              -UseBasicParsing -TimeoutSec 25
    $policy = $resp.Content
    Pass "policy fetched over HTTPS, valid TLS chain, HTTP $($resp.StatusCode)"
    $ctype = $resp.Headers['Content-Type']
    if ($ctype -match 'text/plain') { Pass "content-type $ctype" }
    else { Fail "content-type is '$ctype', must be text/plain" }
} catch {
    Fail "policy fetch failed: $($_.Exception.Message)"
}

if ($policy) {
    $mode   = ([regex]::Match($policy, 'mode:\s*(\w+)')).Groups[1].Value
    $maxAge = ([regex]::Match($policy, 'max_age:\s*(\d+)')).Groups[1].Value
    $polMx  = @([regex]::Matches($policy, 'mx:\s*([^\s]+)') | ForEach-Object { $_.Groups[1].Value })

    if     ($mode -eq 'enforce') { Pass 'mode: enforce' }
    elseif ($mode -eq 'testing') { Warn 'mode: testing - failures reported but mail still delivers' }
    elseif ($mode -eq 'none')    { Warn 'mode: none - MTA-STS effectively disabled' }
    else                         { Fail "unrecognised mode: '$mode'" }

    if ($maxAge) {
        $days = [math]::Round([int]$maxAge / 86400, 1)
        if ($mode -eq 'enforce') {
            Warn "max_age $maxAge (~$days day) - senders cache this, so an MX change needs $days day lead time"
        } else {
            Pass "max_age $maxAge (~$days day)"
        }
    } else {
        Fail 'no max_age in policy'
    }

    # The critical check: every live MX must be covered by a policy mx: pattern.
    if ($polMx.Count -gt 0 -and $liveMx.Count -gt 0) {
        foreach ($mxHost in $liveMx) {
            $covered = $false
            foreach ($pat in $polMx) {
                if ($pat.StartsWith('*.')) {
                    if ($mxHost -like ('*' + $pat.Substring(1))) { $covered = $true }
                } elseif ($mxHost -eq $pat) {
                    $covered = $true
                }
            }
            if ($covered) { Pass "MX $mxHost is covered by policy mx:" }
            else { Fail "MX $mxHost is NOT in the policy - under enforce, senders REFUSE delivery" }
        }
        foreach ($pat in $polMx) {
            if (-not $pat.StartsWith('*.') -and ($liveMx -notcontains $pat)) {
                Warn "policy lists mx: $pat which is not a live MX (stale entry)"
            }
        }
    }
}

# --------------------------------------------------------------- TLS-RPT -----
Head 'TLS-RPT'
$tlsrpt = @(Get-Txt "_smtp._tls.$Domain" | Where-Object { $_ -match 'v=TLSRPTv1' })
if ($tlsrpt.Count -eq 1)     { Pass $tlsrpt[0] }
elseif ($tlsrpt.Count -gt 1) { Fail "$($tlsrpt.Count) TLS-RPT records - must be exactly 1" }
else                         { Fail 'no _smtp._tls record - enforcing MTA-STS with no failure telemetry' }

Head 'Report address reachability'
$allReports = (($dmarc -join '') + ' ' + ($tlsrpt -join ''))
foreach ($m in [regex]::Matches($allReports, 'mailto:([^\s,;!]+)')) {
    $addr = $m.Groups[1].Value
    $rcptDomain = $addr.Split('@')[-1]
    if ($rcptDomain -eq $Domain) {
        Pass "$addr is same-domain, no external authorization record needed"
    } else {
        Warn "$addr is EXTERNAL - requires $Domain._report._dmarc.$rcptDomain to exist"
    }
}

# --------------------------------------------------------------- SUMMARY -----
Write-Host ''
Write-Host ('-' * 70)
if ($script:Failures -gt 0) {
    Write-Host "FAILED - $($script:Failures) failure(s), $($script:Warnings) warning(s)" -ForegroundColor Red
    Write-Host 'Do NOT proceed with an MX change until failures are cleared.' -ForegroundColor Red
    exit 1
}
Write-Host "OK - 0 failures, $($script:Warnings) warning(s)" -ForegroundColor Green
exit 0
