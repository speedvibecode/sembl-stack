# Generates ide/resources/sembl.ico — a 256px dark tile with the sembl cyan mark.
# One-time generator; the committed .ico is the artifact. Re-run if the brand changes.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing

$ideRoot = Split-Path -Parent $PSScriptRoot
$outDir = Join-Path $ideRoot 'resources'
New-Item -ItemType Directory -Force $outDir | Out-Null
$icoPath = Join-Path $outDir 'sembl.ico'

$size = 256
$bmp = New-Object System.Drawing.Bitmap($size, $size)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAlias
$g.Clear([System.Drawing.Color]::Transparent)

# Dark rounded tile
$bg = [System.Drawing.Color]::FromArgb(255, 16, 20, 24)      # #101418
$cyan = [System.Drawing.Color]::FromArgb(255, 124, 212, 223) # #7cd4df (sembl accent)
$r = 52
$path = New-Object System.Drawing.Drawing2D.GraphicsPath
$path.AddArc(0, 0, $r, $r, 180, 90)
$path.AddArc($size - $r - 1, 0, $r, $r, 270, 90)
$path.AddArc($size - $r - 1, $size - $r - 1, $r, $r, 0, 90)
$path.AddArc(0, $size - $r - 1, $r, $r, 90, 90)
$path.CloseFigure()
$g.FillPath((New-Object System.Drawing.SolidBrush($bg)), $path)

# The mark: a bold cyan "S" centered on the tile
$font = New-Object System.Drawing.Font('Segoe UI', 150, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
$fmt = New-Object System.Drawing.StringFormat
$fmt.Alignment = [System.Drawing.StringAlignment]::Center
$fmt.LineAlignment = [System.Drawing.StringAlignment]::Center
$g.DrawString('S', $font, (New-Object System.Drawing.SolidBrush($cyan)), (New-Object System.Drawing.RectangleF(0, -6, $size, $size)), $fmt)

# Thin cyan gate-line under the S (the verify stage motif from the Factory panel)
$pen = New-Object System.Drawing.Pen($cyan, 10)
$g.DrawLine($pen, 70, 208, 186, 208)

$g.Dispose()

# Save as PNG, then wrap in an ICO container (single PNG-compressed 256px entry —
# valid on Vista+ and what modern .ico files do).
$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
$png = $ms.ToArray()
$bmp.Dispose()

$fs = [System.IO.File]::Create($icoPath)
$w = New-Object System.IO.BinaryWriter($fs)
$w.Write([uint16]0)      # reserved
$w.Write([uint16]1)      # type: icon
$w.Write([uint16]1)      # image count
$w.Write([byte]0)        # width 0 = 256
$w.Write([byte]0)        # height 0 = 256
$w.Write([byte]0)        # palette
$w.Write([byte]0)        # reserved
$w.Write([uint16]1)      # planes
$w.Write([uint16]32)     # bpp
$w.Write([uint32]$png.Length)
$w.Write([uint32]22)     # data offset (6 header + 16 entry)
$w.Write($png)
$w.Dispose(); $fs.Dispose()

Write-Host "wrote $icoPath ($((Get-Item $icoPath).Length) bytes)"
