# Watches the BITS job for flux1-dev-fp8.safetensors and commits it to disk
# when the transfer finishes. Runs silently in the background.

$jobName = "FLUX1-dev-fp8"
$destFile = "C:\Users\rvn92\Documents\ComfyUI\models\checkpoints\flux1-dev-fp8.safetensors"
$logFile  = "C:\Users\rvn92\Documents\mtg_deck_builder\flux_dev_download.log"

function Log($msg) {
    $ts = Get-Date -Format "HH:mm:ss"
    "$ts  $msg" | Tee-Object -FilePath $logFile -Append
}

Log "Watcher started — polling BITS job '$jobName' every 30s"

while ($true) {
    $job = Get-BitsTransfer -Name $jobName -ErrorAction SilentlyContinue
    if (-not $job) {
        Log "Job not found — may have already completed or been removed."
        break
    }

    $pct = if ($job.BytesTotal -gt 0) { [math]::Round($job.BytesTransferred / $job.BytesTotal * 100, 1) } else { 0 }
    Log "State=$($job.JobState)  $([math]::Round($job.BytesTransferred/1GB,2))/$([math]::Round($job.BytesTotal/1GB,2)) GB  ($pct%)"

    switch ($job.JobState) {
        "Transferred" {
            Log "Transfer complete — committing to disk..."
            $job | Complete-BitsTransfer
            if (Test-Path $destFile) {
                $sizeMB = [math]::Round((Get-Item $destFile).Length / 1GB, 2)
                Log "SUCCESS — flux1-dev-fp8.safetensors saved ($sizeMB GB)"
                Log "Restart ComfyUI for the new checkpoint to appear."
            } else {
                Log "ERROR — Complete-BitsTransfer ran but file not found at $destFile"
            }
            exit 0
        }
        "Error" {
            Log "ERROR — BITS job failed: $($job.ErrorDescription)"
            Log "To retry: Remove-BitsTransfer job then re-run start_app.bat or re-download manually."
            exit 1
        }
        "Suspended" {
            Log "Job suspended — resuming..."
            $job | Resume-BitsTransfer
        }
    }

    Start-Sleep -Seconds 30
}
