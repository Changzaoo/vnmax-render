# Prepara o GitHub do Bitcoin VNMAX no notebook, SEPARADO da RP Líder (login próprio, pasta própria, identidade só no repositório).
# Uso: powershell -NoProfile -ExecutionPolicy Bypass -File instalar-vnmax-github.ps1 [-InstalarGh]
# O único passo manual é o seu clique no navegador (confirmar o código do GitHub, na conta Changzaoo). Não digita senha por você.
param([switch]$InstalarGh)
$ErrorActionPreference = "Stop"
$base = Join-Path $env:USERPROFILE "vnmax"
$cfg  = Join-Path $env:USERPROFILE ".config\gh-vnmax"
New-Item -ItemType Directory -Force $base, $cfg | Out-Null
$env:GH_CONFIG_DIR = $cfg                    # login do VNMAX isolado: o login da RP Líder não é tocado

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
  if ($InstalarGh) {
    winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
  }
  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host "GitHub CLI (gh) não encontrado. Rode de novo com -InstalarGh (instala o gh oficial via winget) ou instale à mão."
    exit 2
  }
}

$u = ""
try { $u = (gh api user --jq .login 2>$null) } catch { $u = "" }
if ($u -ne "Changzaoo") {
  Write-Host ""
  Write-Host ">>> Vai abrir o navegador. Entre na conta Changzaoo (NÃO a da RP Líder), digite o código que aparece abaixo e confirme."
  Start-Process "https://github.com/login/device"
  gh auth login --hostname github.com --git-protocol https --web
  $u = (gh api user --jq .login)
}
if ($u -ne "Changzaoo") {
  Write-Host "Conta errada ($u). Saia dessa conta no navegador e entre com a Changzaoo. Nada foi baixado."
  exit 3
}

$dest = Join-Path $base "aprendabitcoin"
if (-not (Test-Path (Join-Path $dest ".git"))) {
  git -c credential.helper= -c "credential.helper=!gh auth git-credential" clone https://github.com/Changzaoo/aprendabitcoin.git $dest
}
git -C $dest config user.name vinicius
git -C $dest config user.email vinicius@local
Write-Host ""
Write-Host "Pronto. Conta: $u | projeto: $dest"
Write-Host "Em terminais novos, antes de usar gh/git push nesse projeto: `$env:GH_CONFIG_DIR = '$cfg'"
