# 本地发布脚本：打包 zip、创建 GitHub Release 并上传
# 用法: .\scripts\publish.ps1 -Version v1.0.0

param(
    [Parameter(Mandatory = $true)]
    [string]$Version
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Building exe..."
taskkill /IM DeltaResolutionSwitcher.exe /F 2>$null | Out-Null
python -m pip install -r requirements.txt pyinstaller -q
python -m PyInstaller DeltaResolutionSwitcher.spec --noconfirm --clean
Copy-Item -Force config.json dist\config.json
Copy-Item -Recurse -Force assets dist\assets

$zipName = "DeltaResolutionSwitcher-$Version.zip"
$zipPath = Join-Path "release" $zipName
New-Item -ItemType Directory -Force -Path release | Out-Null
Compress-Archive -Path dist\DeltaResolutionSwitcher.exe, dist\config.json, dist\assets `
    -DestinationPath $zipPath -Force

Write-Host "Creating git tag $Version..."
git tag -a $Version -m "Release $Version" -f

Write-Host "Pushing tag (triggers GitHub Actions build)..."
git push origin $Version

Write-Host ""
Write-Host "Done. If Actions is configured, the release asset will appear at:"
Write-Host "https://github.com/Misoryan/delta-force-resolution-switcher/releases/tag/$Version"
Write-Host ""
Write-Host "To upload manually instead:"
Write-Host "  gh release create $Version `"$zipPath`" --title `"Release $Version`""
