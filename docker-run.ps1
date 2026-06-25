# Simple Docker build and compose script for Windows PowerShell

# Check if .env exists
if (-not (Test-Path ".env")) {
    Write-Host "ERROR: .env file not found!" -ForegroundColor Red
    exit 1
}

# Read .env file
$env = @{}
Get-Content ".env" | Where-Object { $_ -and -not $_.StartsWith("#") } | ForEach-Object {
    $parts = $_ -split "=", 2
    if ($parts.Count -eq 2) {
        $key = $parts[0].Trim()
        $value = $parts[1].Trim().Trim('"').Trim("'")
        $env[$key] = $value
    }
}

$supabaseUrl = $env['VITE_SUPABASE_URL']
$supabaseKey = $env['VITE_SUPABASE_PUBLISHABLE_KEY']

if (-not $supabaseUrl -or -not $supabaseKey) {
    Write-Host "ERROR: Missing Supabase credentials in .env!" -ForegroundColor Red
    exit 1
}

Write-Host "Building frontend..."
Write-Host "Build args:"
Write-Host "  VITE_SUPABASE_URL=$supabaseUrl"
Write-Host "  VITE_SUPABASE_PUBLISHABLE_KEY=(set, value hidden)"
Write-Host "  VITE_API_URL=http://backend:8000/api"
Write-Host ""

# Build frontend with explicit build args
docker build --build-arg "VITE_SUPABASE_URL=$supabaseUrl" --build-arg "VITE_SUPABASE_PUBLISHABLE_KEY=$supabaseKey" --build-arg "VITE_API_URL=http://backend:8000/api" -t volarbmodel-frontend -f Dockerfile .

if ($LASTEXITCODE -ne 0) {
    Write-Host "Frontend build failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Building backend..."
docker build -t volarbmodel-backend ./backend

if ($LASTEXITCODE -ne 0) {
    Write-Host "Backend build failed!" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Stopping existing containers..."
docker-compose down --remove-orphans

Write-Host ""
Write-Host "Starting containers with docker-compose..."
docker-compose up
