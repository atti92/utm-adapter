[CmdletBinding()]
param(
    [string] $MissionPlannerRoot,
    [string] $ConnectorUrl = "http://127.0.0.1:8000",
    [string] $VehicleId = "sitl-1",
    [switch] $SkipConnector,
    [switch] $AllowDegraded
)

$ErrorActionPreference = "Stop"

function Find-MissionPlannerRoot {
    $programFiles = [Environment]::GetEnvironmentVariable("ProgramFiles")
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    $localAppData = [Environment]::GetEnvironmentVariable("LOCALAPPDATA")
    $candidates = @(
        $env:MISSION_PLANNER_ROOT,
        $MissionPlannerRoot
    )
    if ($programFiles) {
        $candidates += Join-Path $programFiles "Mission Planner"
    }
    if ($programFilesX86) {
        $candidates += Join-Path $programFilesX86 "Mission Planner"
    }
    if ($localAppData) {
        $candidates += Join-Path $localAppData "Mission Planner"
    }

    foreach ($candidate in ($candidates | Where-Object { $_ -and $_.Trim() } | Select-Object -Unique)) {
        $resolved = Resolve-Path -LiteralPath $candidate -ErrorAction SilentlyContinue
        if ($resolved -and (Test-Path -LiteralPath (Join-Path $resolved "MissionPlanner.exe") -PathType Leaf)) {
            return $resolved.Path
        }
    }

    throw "Mission Planner was not found. Pass -MissionPlannerRoot 'C:\Path\To\Mission Planner' or set MISSION_PLANNER_ROOT."
}

function Invoke-ConnectorJson {
    param(
        [Parameter(Mandatory = $true)]
        [string] $BaseUrl,
        [Parameter(Mandatory = $true)]
        [string] $Path
    )

    Invoke-RestMethod -Uri ($BaseUrl.TrimEnd("/") + $Path) -Method Get -TimeoutSec 5
}

$root = Find-MissionPlannerRoot
$executable = Join-Path $root "MissionPlanner.exe"
$plugin = Join-Path $root "plugins\UtmConnectorPlugin.cs"

if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Mission Planner executable is missing: $executable"
}
if (-not (Test-Path -LiteralPath $plugin -PathType Leaf)) {
    throw "UTM Connector plugin is not installed at $plugin. Run Install-UtmConnectorPlugin.ps1 first."
}

Write-Host "[ok] Mission Planner: $root"
Write-Host "[ok] UTM Connector plugin: $plugin"

if ($SkipConnector) {
    Write-Host "[info] connector checks skipped"
    Write-Host "Installation check passed. Start Mission Planner and open UTM Connector from the main toolbar."
    exit 0
}

$baseCandidates = @($ConnectorUrl.TrimEnd("/"))
if ($ConnectorUrl.TrimEnd("/") -eq "http://127.0.0.1:8000") {
    $baseCandidates += "http://127.0.0.1:8001"
}

$selectedBase = $null
$health = $null
$lastError = $null
foreach ($candidate in ($baseCandidates | Select-Object -Unique)) {
    try {
        $health = Invoke-ConnectorJson -BaseUrl $candidate -Path "/v1/health"
        $selectedBase = $candidate
        break
    }
    catch {
        $lastError = $_.Exception.Message
    }
}

if (-not $selectedBase) {
    throw "The connector is unreachable at $($baseCandidates -join ', '). Last error: $lastError"
}

if ($health.status -ne "ok") {
    if (-not $AllowDegraded) {
        throw "The connector responded at $selectedBase but is $($health.status). Re-run with -AllowDegraded only when checking startup recovery."
    }
    Write-Warning "connector status is $($health.status)"
}
else {
    Write-Host "[ok] connector health: $selectedBase ($($health.status))"
}

$vehicles = @(Invoke-ConnectorJson -BaseUrl $selectedBase -Path "/v1/vehicles")
$vehicle = $vehicles | Where-Object { $_.vehicle_id -eq $VehicleId } | Select-Object -First 1
if (-not $vehicle) {
    throw "Vehicle '$VehicleId' is not visible through the connector at $selectedBase. Check MAVLink routing and the vehicle ID."
}
if ($vehicle.connection_state -ne "CONNECTED") {
    throw "Vehicle '$VehicleId' is visible but not connected (state: $($vehicle.connection_state), quality: $($vehicle.quality))."
}

Write-Host "[ok] vehicle ${VehicleId}: connected (quality: $($vehicle.quality))"
Write-Host "Smoke check passed. Restart Mission Planner if needed, then use the UTM Connector toolbar menu."
