Add-Type -AssemblyName System.Drawing

$backgroundPath = 'C:\Users\moses\.codex\generated_images\01a0d74a-2049-7c00-82ad-2fb28bb753b3\exec-a0bd1f9e-b1c2-49d5-ad5b-1f332db9fdd2.png'
$heroSourcePath = 'C:\Users\moses\.codex\generated_images\01a0d74a-2049-7c00-82ad-2fb28bb753b3\exec-3ea5c965-cdee-4d78-8f4b-3c21bc4e4d89.png'
$outputPath = 'D:\JQE\40-days-of-prayer-3000x300-banner.png'

$canvasWidth = 3000
$canvasHeight = 300
$canvas = New-Object System.Drawing.Bitmap($canvasWidth, $canvasHeight)
$graphics = [System.Drawing.Graphics]::FromImage($canvas)
$graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
$graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
$graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
$graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit

$background = [System.Drawing.Image]::FromFile($backgroundPath)
$heroSource = [System.Drawing.Image]::FromFile($heroSourcePath)
$heroCutout = New-Object System.Drawing.Bitmap($heroSource.Width, $heroSource.Height, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
for ($py = 0; $py -lt $heroSource.Height; $py++) {
    for ($px = 0; $px -lt $heroSource.Width; $px++) {
        $pixel = ([System.Drawing.Bitmap]$heroSource).GetPixel($px, $py)
        $isMagenta = ($pixel.R -gt 165 -and $pixel.B -gt 165 -and $pixel.G -lt 155 -and $pixel.R -gt ($pixel.G + 55) -and $pixel.B -gt ($pixel.G + 55))
        if ($isMagenta) { $heroCutout.SetPixel($px, $py, [System.Drawing.Color]::FromArgb(0, 0, 0, 0)) }
        else { $heroCutout.SetPixel($px, $py, $pixel) }
    }
}

$graphics.DrawImage($background, [System.Drawing.Rectangle]::new(0, 0, $canvasWidth, $canvasHeight), [System.Drawing.Rectangle]::new(0, 0, $background.Width, $background.Height), [System.Drawing.GraphicsUnit]::Pixel)

$navyOverlay = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(92, 0, 8, 28))
$graphics.FillRectangle($navyOverlay, 0, 0, $canvasWidth, $canvasHeight)
$navyOverlay.Dispose()

$heroRect = [System.Drawing.Rectangle]::new(0, -18, 520, 740)
$graphics.DrawImage($heroCutout, $heroRect)

$fade = New-Object System.Drawing.Drawing2D.LinearGradientBrush([System.Drawing.Rectangle]::new(340, 0, 430, 300), [System.Drawing.Color]::FromArgb(0, 0, 8, 20), [System.Drawing.Color]::FromArgb(240, 2, 10, 28), [System.Drawing.Drawing2D.LinearGradientMode]::Horizontal)
$graphics.FillRectangle($fade, 330, 0, 360, 300)
$fade.Dispose()

$gold = [System.Drawing.Color]::FromArgb(255, 242, 194, 65)
$cream = [System.Drawing.Color]::FromArgb(255, 255, 250, 236)
$muted = [System.Drawing.Color]::FromArgb(255, 205, 220, 231)
$dark = [System.Drawing.Color]::FromArgb(210, 1, 8, 23)

function Draw-Text($Text, $FontName, $Size, $Style, $Color, $X, $Y, $W, $H, $Alignment = 'Near') {
    $font = New-Object System.Drawing.Font($FontName, $Size, $Style, [System.Drawing.GraphicsUnit]::Pixel)
    $brush = New-Object System.Drawing.SolidBrush($Color)
    $format = New-Object System.Drawing.StringFormat
    if ($Alignment -eq 'Center') { $format.Alignment = [System.Drawing.StringAlignment]::Center }
    elseif ($Alignment -eq 'Far') { $format.Alignment = [System.Drawing.StringAlignment]::Far }
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    $graphics.DrawString($Text, $font, $brush, [System.Drawing.RectangleF]::new($X, $Y, $W, $H), $format)
    $format.Dispose(); $brush.Dispose(); $font.Dispose()
}

$headerFont = [System.Drawing.FontStyle]::Bold
$graphics.FillRectangle((New-Object System.Drawing.SolidBrush($gold)), 555, 19, 390, 2)
Draw-Text 'MILITIA OF THE IMMACULATA' 'Georgia' 22 $headerFont $cream 965 2 960 34 'Center'
$graphics.FillRectangle((New-Object System.Drawing.SolidBrush($gold)), 1945, 19, 90, 2)

Draw-Text '40' 'Georgia' 122 $headerFont $gold 545 30 300 130 'Center'
$clockPen = New-Object System.Drawing.Pen($gold, 3)
$graphics.DrawEllipse($clockPen, 785, 47, 72, 72)
$graphics.DrawLine($clockPen, 821, 83, 821, 59)
$graphics.DrawLine($clockPen, 821, 83, 840, 93)
$clockPen.Dispose()
Draw-Text 'DAYS OF PRAYER' 'Arial' 72 $headerFont $cream 875 44 950 92 'Near'
Draw-Text 'MIDNIGHT PRAYER  •  5TH EDITION 2026' 'Arial' 25 $headerFont $muted 875 126 950 34 'Near'

$linePen = New-Object System.Drawing.Pen($gold, 2)
$graphics.DrawLine($linePen, 875, 166, 2020, 166)
$linePen.Dispose()

Draw-Text '27TH SEPTEMBER TO 5TH NOVEMBER, 2026' 'Georgia' 28 $headerFont $cream 545 174 900 40 'Near'
Draw-Text 'DAY 1  •  12:00 AM – 1:00 AM' 'Arial' 36 $headerFont $gold 1435 174 630 40 'Near'

$infoBg = New-Object System.Drawing.SolidBrush($dark)
$graphics.FillRectangle($infoBg, 2110, 27, 855, 245)
$infoBg.Dispose()
$infoPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(190, 242, 194, 65), 2)
$graphics.DrawRectangle($infoPen, 2110, 27, 855, 245)
$infoPen.Dispose()
Draw-Text 'JOIN ON ZOOM' 'Arial' 36 $headerFont $cream 2160 36 720 48 'Near'
Draw-Text 'MEETING ID: 827 7670 8701' 'Arial' 27 $headerFont $muted 2160 94 770 36 'Near'
Draw-Text 'PASSCODE: FATIMA' 'Arial' 27 $headerFont $gold 2160 134 770 36 'Near'
Draw-Text '+256773708984 / +256702271340' 'Arial' 24 $headerFont $cream 2160 196 770 38 'Near'

$graphics.DrawLine((New-Object System.Drawing.Pen($gold, 2)), 2160, 180, 2905, 180)
$canvas.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose(); $background.Dispose(); $heroSource.Dispose(); $heroCutout.Dispose(); $canvas.Dispose()
