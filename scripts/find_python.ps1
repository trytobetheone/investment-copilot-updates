$ErrorActionPreference = 'SilentlyContinue'

function Test-PythonExecutable([string]$Exe, [string[]]$Args = @()) {
    try {
        $code = @'
import sys
ok = (3, 11) <= sys.version_info[:2] <= (3, 14)
if not ok:
    raise SystemExit(2)
print(sys.executable)
'@
        $out = & $Exe @Args -c $code 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) {
            $path = ($out | Select-Object -Last 1).Trim()
            if (Test-Path -LiteralPath $path) {
                return $path
            }
        }
    } catch {}
    return $null
}

# 1) Python Launcher, if present. Resolve it to the REAL python.exe path.
$py = Get-Command py.exe -ErrorAction SilentlyContinue
if ($py) {
    foreach ($ver in @('3.14','3.13','3.12','3.11')) {
        $found = Test-PythonExecutable $py.Source @("-$ver")
        if ($found) { Write-Output $found; exit 0 }
    }
}

# 2) python/python3 commands on PATH.
foreach ($name in @('python.exe','python3.exe','python','python3')) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) {
        $found = Test-PythonExecutable $cmd.Source
        if ($found) { Write-Output $found; exit 0 }
    }
}

# 3) Standard python.org install paths (per-user + machine-wide).
$roots = @(
    "$env:LocalAppData\Programs\Python",
    "$env:ProgramFiles\Python",
    "$env:ProgramFiles"
)
if (${env:ProgramFiles(x86)}) { $roots += "${env:ProgramFiles(x86)}\Python" }

foreach ($root in $roots) {
    if (-not $root -or -not (Test-Path -LiteralPath $root)) { continue }
    $patterns = @(
        "$root\Python314\python.exe",
        "$root\Python313\python.exe",
        "$root\Python312\python.exe",
        "$root\Python311\python.exe",
        "$root\Python314-*\python.exe",
        "$root\Python313-*\python.exe",
        "$root\Python312-*\python.exe",
        "$root\Python311-*\python.exe"
    )
    foreach ($pattern in $patterns) {
        foreach ($candidate in Get-Item $pattern -ErrorAction SilentlyContinue) {
            $found = Test-PythonExecutable $candidate.FullName
            if ($found) { Write-Output $found; exit 0 }
        }
    }
}

# 4) Registry registrations made by python.org installers.
$regBases = @(
    'HKCU:\Software\Python\PythonCore',
    'HKLM:\Software\Python\PythonCore',
    'HKLM:\Software\WOW6432Node\Python\PythonCore'
)
foreach ($base in $regBases) {
    foreach ($ver in @('3.14','3.13','3.12','3.11')) {
        $key = Join-Path $base "$ver\InstallPath"
        try {
            $dir = (Get-ItemProperty -Path $key -ErrorAction Stop).'(default)'
            if (-not $dir) { $dir = (Get-Item -Path $key -ErrorAction Stop).GetValue('') }
            if ($dir) {
                $candidate = Join-Path $dir 'python.exe'
                $found = Test-PythonExecutable $candidate
                if ($found) { Write-Output $found; exit 0 }
            }
        } catch {}
    }
}

exit 1
