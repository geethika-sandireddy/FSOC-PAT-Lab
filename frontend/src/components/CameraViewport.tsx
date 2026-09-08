import { useRef, useEffect } from 'react'

interface CameraViewportProps {
  frameData?: any
}

export default function CameraViewport({ frameData }: CameraViewportProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Draw default black screen with grid
    ctx.fillStyle = '#0a0e27'
    ctx.fillRect(0, 0, canvas.width, canvas.height)

    // Grid pattern
    ctx.strokeStyle = '#1e293b'
    ctx.lineWidth = 0.5
    for (let i = 0; i < canvas.width; i += 40) {
      ctx.beginPath()
      ctx.moveTo(i, 0)
      ctx.lineTo(i, canvas.height)
      ctx.stroke()
    }
    for (let i = 0; i < canvas.height; i += 40) {
      ctx.beginPath()
      ctx.moveTo(0, i)
      ctx.lineTo(canvas.width, i)
      ctx.stroke()
    }

    // Draw HUD overlays
    const cx = canvas.width / 2
    const cy = canvas.height / 2

    // Crosshair
    ctx.strokeStyle = '#00d4aa'
    ctx.lineWidth = 1
    ctx.beginPath()
    ctx.moveTo(cx - 30, cy)
    ctx.lineTo(cx + 30, cy)
    ctx.moveTo(cx, cy - 30)
    ctx.lineTo(cx, cy + 30)
    ctx.stroke()

    // Beacon ring
    ctx.beginPath()
    ctx.arc(cx, cy, 35, 0, Math.PI * 2)
    ctx.stroke()

    // Inner circle
    ctx.beginPath()
    ctx.arc(cx, cy, 15, 0, Math.PI * 2)
    ctx.stroke()

    // Center dot
    ctx.fillStyle = '#00d4aa'
    ctx.beginPath()
    ctx.arc(cx, cy, 3, 0, Math.PI * 2)
    ctx.fill()

    // Corner marks
    ctx.strokeStyle = '#4b5563'
    ctx.lineWidth = 1
    const corners = [
      { x: 20, y: 20, sx: 1, sy: 1 },
      { x: canvas.width - 20, y: 20, sx: -1, sy: 1 },
      { x: 20, y: canvas.height - 20, sx: 1, sy: -1 },
      { x: canvas.width - 20, y: canvas.height - 20, sx: -1, sy: -1 },
    ]
    corners.forEach(({ x, y, sx, sy }) => {
      ctx.beginPath()
      ctx.moveTo(x, y)
      ctx.lineTo(x + sx * 25, y)
      ctx.moveTo(x, y)
      ctx.lineTo(x, y + sy * 25)
      ctx.stroke()
    })
  }, [frameData])

  return (
    <div className="w-full h-full flex items-center justify-center bg-black relative">
      <canvas
        ref={canvasRef}
        width={640}
        height={480}
        className="max-w-full max-h-full scanline"
      />
      <div className="absolute bottom-4 left-4 flex gap-2 items-center">
        <div className="status-chip locked">● LOCKED</div>
        <div className="text-xs text-slate-400">BEACON ACQUIRED · TRACKING ACTIVE</div>
      </div>
      <div className="absolute top-4 right-4 text-xs text-slate-400">
        <div>FSOC Virtual Environment</div>
        <div className="text-cyan-400 font-mono mt-1">640×480 @ 30 Hz</div>
      </div>
    </div>
  )
}
