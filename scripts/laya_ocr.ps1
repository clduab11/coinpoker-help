param([string]$Language = "en-US", [switch]$Persistent)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Invoke-OcrRequest([string]$inputText, $engine, $asTask) {
    function Complete-OcrOperation($operation, [Type]$type) {
        $task = $asTask.MakeGenericMethod($type).Invoke($null, @($operation))
        if (-not $task.Wait(10000)) { throw "windows-ocr-operation-timeout" }
        return $task.GetAwaiter().GetResult()
    }
    if ($inputText.Length -gt 16000000) { throw "windows-ocr-input-too-large" }
    $request = $inputText | ConvertFrom-Json
    if (@($request.images).Count -lt 1 -or @($request.images).Count -gt 12) { throw "windows-ocr-invalid-batch" }
    $images = @()
    foreach ($item in $request.images) {
        if ($item.id -notmatch '^[a-z0-9_]{1,32}$') { throw "windows-ocr-invalid-image-id" }
        $bytes = [Convert]::FromBase64String($item.png)
        if ($bytes.Length -gt 8388608) { throw "windows-ocr-png-too-large" }
        $stream = [Windows.Storage.Streams.InMemoryRandomAccessStream]::new()
        $writer = [Windows.Storage.Streams.DataWriter]::new($stream)
        $bitmap = $null
        try {
            $writer.WriteBytes($bytes)
            $null = Complete-OcrOperation ($writer.StoreAsync()) ([uint32])
            $null = $writer.DetachStream()
            $stream.Seek(0)
            $decoder = Complete-OcrOperation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
            if ($decoder.PixelWidth -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension -or
                $decoder.PixelHeight -gt [Windows.Media.Ocr.OcrEngine]::MaxImageDimension) {
                throw "windows-ocr-image-dimension-limit"
            }
            $bitmap = Complete-OcrOperation ($decoder.GetSoftwareBitmapAsync(
                [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
                [Windows.Graphics.Imaging.BitmapAlphaMode]::Ignore)) ([Windows.Graphics.Imaging.SoftwareBitmap])
            $result = Complete-OcrOperation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
            $words = @()
            $lineIndex = 0
            foreach ($line in $result.Lines) {
                foreach ($word in $line.Words) {
                    $rect = $word.BoundingRect
                    $words += @{text=$word.Text; line=$lineIndex; bbox=@(
                        $rect.X, $rect.Y, ($rect.X + $rect.Width), ($rect.Y + $rect.Height))}
                }
                $lineIndex++
            }
            $angle = if ($null -eq $result.TextAngle) { 0.0 } else { [double]$result.TextAngle }
            $images += @{id=$item.id; width=$decoder.PixelWidth; height=$decoder.PixelHeight;
                         text_angle=$angle; words=$words}
        } finally {
            if ($null -ne $bitmap) { $bitmap.Dispose() }
            $writer.Dispose()
            $stream.Dispose()
        }
    }
    return (@{schema_version=1; status="ok"; method="windows_media_ocr_cpu";
              language=$engine.RecognizerLanguage.LanguageTag;
              max_image_dimension=[Windows.Media.Ocr.OcrEngine]::MaxImageDimension;
              images=$images} | ConvertTo-Json -Depth 8 -Compress)
}

try {
    Add-Type -AssemblyName System.Runtime.WindowsRuntime
    $null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
    $null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
    $null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
    $null = [Windows.Storage.Streams.DataWriter, Windows.Storage.Streams, ContentType=WindowsRuntime]
    $null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
    $null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
    $asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq "AsTask" -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
    }
    if (@($asTask).Count -ne 1) { throw "windows-ocr-async-adapter-unavailable" }
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new($Language))
    if ($null -eq $engine) { throw "windows-ocr-language-unavailable:$Language" }
    if ($Persistent) {
        while ($null -ne ($line = [Console]::In.ReadLine())) {
            if ($line.Length -eq 0) { continue }
            try {
                [Console]::Out.WriteLine((Invoke-OcrRequest $line $engine $asTask))
            } catch {
                [Console]::Out.WriteLine((@{schema_version=1; status="unavailable"; method="windows_media_ocr_cpu";
                    reason=$_.Exception.Message; images=@()} | ConvertTo-Json -Depth 4 -Compress))
            }
            [Console]::Out.Flush()
        }
    } else {
        $inputText = [Console]::In.ReadToEnd()
        Invoke-OcrRequest $inputText $engine $asTask
    }
} catch {
    @{schema_version=1; status="unavailable"; method="windows_media_ocr_cpu";
      reason=$_.Exception.Message; images=@()} | ConvertTo-Json -Depth 4 -Compress
    exit 1
}
