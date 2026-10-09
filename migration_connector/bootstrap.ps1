[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [string]$BootstrapFile,

    [string]$KubeContext = "",

    [string]$ChartPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Require-Command {
    param([Parameter(Mandatory)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command is unavailable: $Name"
    }
}

Require-Command kubectl
Require-Command helm

$resolvedBootstrap = (Resolve-Path -LiteralPath $BootstrapFile).Path
$bootstrap = Get-Content -LiteralPath $resolvedBootstrap -Raw |
    ConvertFrom-Json

if ($bootstrap.apiBaseUrl -notmatch '^https://[A-Za-z0-9.-]+(?::[0-9]+)?(?:/[A-Za-z0-9._~!$&''()*+,;=:@%/-]*)?$') {
    throw "The Navigan API URL must use HTTPS."
}
if ($bootstrap.sourceClusterId -notmatch '^SRC-[a-f0-9]{32}$') {
    throw "The source cluster ID is invalid."
}
if ($bootstrap.enrollmentToken -notmatch '^[A-Za-z0-9_-]{43,128}$') {
    throw "The enrollment token is invalid."
}
if ($bootstrap.imageDigest -notmatch '^sha256:[a-f0-9]{64}$') {
    throw "The connector image digest is invalid."
}
if ([string]::IsNullOrWhiteSpace($bootstrap.imageRepository)) {
    throw "The connector image repository is missing."
}

if ([string]::IsNullOrWhiteSpace($ChartPath)) {
    $ChartPath = Join-Path $PSScriptRoot "helm"
}
$resolvedChart = (Resolve-Path -LiteralPath $ChartPath).Path

$kubectlArgs = @()
$helmArgs = @()
if (-not [string]::IsNullOrWhiteSpace($KubeContext)) {
    $kubectlArgs += @("--context", $KubeContext)
    $helmArgs += @("--kube-context", $KubeContext)
}

& kubectl @kubectlArgs auth can-i get --raw=/version |
    Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "The selected kubeconfig context cannot access the cluster."
}

$enrollmentBody = @{
    sourceClusterId = $bootstrap.sourceClusterId
    enrollmentToken = $bootstrap.enrollmentToken
} | ConvertTo-Json -Compress

$enrollment = Invoke-RestMethod `
    -Method Post `
    -Uri "$($bootstrap.apiBaseUrl.TrimEnd('/'))/source-connectors/enroll" `
    -ContentType "application/json" `
    -Body $enrollmentBody `
    -MaximumRedirection 0

if ($enrollment.connectorId -notmatch '^SCC-[a-f0-9]{32}$') {
    throw "Navigan returned an invalid connector identity."
}
if ($enrollment.connectorToken -notmatch '^[A-Za-z0-9_-]{43,128}$') {
    throw "Navigan returned an invalid connector credential."
}

$namespace = "navigan-migration"
$secretName = "navigan-source-connector-credentials"
$secretToken = [Convert]::ToBase64String(
    [Text.Encoding]::UTF8.GetBytes($enrollment.connectorToken)
)
$secretManifest = @"
apiVersion: v1
kind: Secret
metadata:
  name: $secretName
  namespace: $namespace
type: Opaque
data:
  connector-token: $secretToken
"@

& kubectl @kubectlArgs create namespace $namespace `
    --dry-run=client -o yaml |
    & kubectl @kubectlArgs apply -f -
if ($LASTEXITCODE -ne 0) {
    throw "Unable to prepare the Navigan connector namespace."
}

$secretManifest |
    & kubectl @kubectlArgs apply -f -
if ($LASTEXITCODE -ne 0) {
    throw "Unable to store the connector credential in Kubernetes."
}

& helm @helmArgs upgrade --install navigan-source-connector `
    $resolvedChart `
    --namespace $namespace `
    --set-string "image.repository=$($bootstrap.imageRepository)" `
    --set-string "image.digest=$($bootstrap.imageDigest)" `
    --set-string "navigan.apiBaseUrl=$($bootstrap.apiBaseUrl)" `
    --set-string "navigan.connectorId=$($enrollment.connectorId)" `
    --set-string "navigan.credentialsSecretName=$secretName" `
    --wait `
    --timeout 5m
if ($LASTEXITCODE -ne 0) {
    throw "The Navigan source connector installation failed."
}

Clear-Content -LiteralPath $resolvedBootstrap
Remove-Item -LiteralPath $resolvedBootstrap

Write-Host "SUCCESS: source connector installed."
Write-Host "Source cluster: $($bootstrap.sourceClusterId)"
Write-Host "Connector: $($enrollment.connectorId)"
