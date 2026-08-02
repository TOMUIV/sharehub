$dd = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
if (Test-Path $dd) { Start-Process $dd }
$ok = 0; $ready = $false
for ($i = 0; $i -lt 90; $i++) {
    docker version --format OK *> $null
    if ($LASTEXITCODE -eq 0) { $ok++; if ($ok -ge 3) { $ready = $true; break } } else { $ok = 0 }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Write-Output "RESULT= daemon not ready"; exit 1 }
Write-Output "RESULT= daemon ready"

docker rm -f sh_test 2>$null | Out-Null
docker run -d --name sh_test -p 18888:18888 sharehub/sharehub:latest 2>&1 | Out-String
Start-Sleep -Seconds 4
Write-Output "=== HTTP / ==="
$r = curl.exe -s -o NUL -w "%{http_code}" http://127.0.0.1:18888/
Write-Output "public_http=$r"
Write-Output "=== logs ==="
docker logs sh_test 2>&1 | Out-String
Write-Output "=== run test ==="
docker run --rm sharehub/sharehub:latest python3 -c "print('container-python-ok')" 2>&1 | Out-String
docker rm -f sh_test 2>$null | Out-Null
