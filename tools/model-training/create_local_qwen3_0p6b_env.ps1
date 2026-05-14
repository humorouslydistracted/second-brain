param(
    [string]$EnvDir = ".venv-qwen3-0p6b-1650",
    [string]$TorchIndexUrl = "https://download.pytorch.org/whl/cu128"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$RequirementsPath = Join-Path $ProjectRoot "requirements_local_qwen3_0p6b_windows.txt"

Write-Host "Creating local Windows env for Qwen3-0.6B GTX1650 experiments..."
python -m venv $EnvDir

$PythonExe = Join-Path $EnvDir "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    throw "Could not find venv python at $PythonExe"
}

& $PythonExe -m pip install --upgrade pip setuptools wheel

Write-Host "Installing CUDA-enabled PyTorch from $TorchIndexUrl"
& $PythonExe -m pip install torch torchvision torchaudio --index-url $TorchIndexUrl

Write-Host "Installing Unsloth Windows build"
& $PythonExe -m pip install "unsloth[windows] @ git+https://github.com/unslothai/unsloth.git"

Write-Host "Installing training dependencies"
& $PythonExe -m pip install -r $RequirementsPath

Write-Host ""
Write-Host "Environment ready."
Write-Host "Activate it with:"
Write-Host "  $EnvDir\Scripts\Activate.ps1"
Write-Host ""
Write-Host "If your NVIDIA driver cannot use cu128 wheels, rerun with a different index URL."
Write-Host "Example:"
Write-Host "  .\create_local_qwen3_0p6b_env.ps1 -TorchIndexUrl https://download.pytorch.org/whl/cu124"
