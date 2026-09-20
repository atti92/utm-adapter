[CmdletBinding()]
param(
    [string] $MissionPlannerRoot,
    [switch] $Force
)

$ErrorActionPreference = "Stop"

$source = Join-Path $PSScriptRoot "UtmConnectorPlugin.cs"
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
    throw "The plugin source was not found: $source"
}

function Find-MissionPlannerRoot {
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $candidates = @(
        $env:MISSION_PLANNER_ROOT,
        $MissionPlannerRoot,
        (Join-Path $env:ProgramFiles "Mission Planner"),
        (Join-Path $programFilesX86 "Mission Planner"),
        (Join-Path $env:LOCALAPPDATA "Mission Planner")
    ) | Where-Object { $_ -and $_.Trim() } | Select-Object -Unique

    foreach ($candidate in $candidates) {
        $resolved = Resolve-Path -LiteralPath $candidate -ErrorAction SilentlyContinue
        if ($resolved -and (Test-Path -LiteralPath (Join-Path $resolved "MissionPlanner.exe") -PathType Leaf)) {
            return $resolved.Path
        }
    }

    throw "Mission Planner was not found. Pass -MissionPlannerRoot 'C:\Path\To\Mission Planner' or set MISSION_PLANNER_ROOT."
}

$root = Find-MissionPlannerRoot
$pluginDirectory = Join-Path $root "plugins"
$target = Join-Path $pluginDirectory "UtmConnectorPlugin.cs"

New-Item -ItemType Directory -Path $pluginDirectory -Force | Out-Null
if ((Test-Path -LiteralPath $target -PathType Leaf) -and -not $Force) {
    throw "The plugin already exists at $target. Re-run with -Force to replace it; the old file will be backed up."
}

if (Test-Path -LiteralPath $target -PathType Leaf) {
    $backup = "$target.bak"
    Copy-Item -LiteralPath $target -Destination $backup -Force
    Write-Host "Backed up the existing plugin to $backup"
}

Copy-Item -LiteralPath $source -Destination $target -Force
Write-Host "Installed UTM Connector Mission Planner plugin at $target"
Write-Host "Restart Mission Planner, then open Flight Data > UTM Connector."
