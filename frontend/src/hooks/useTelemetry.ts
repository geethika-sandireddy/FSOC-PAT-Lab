import { useState, useEffect } from 'react'

export function useTelemetry() {
  const [data, setData] = useState({
    state: 'LOCKED',
    rxPower: -11.4,
    snr: 73.6,
    margin: 38.6,
    pointingError: 1.5,
    confidence: 95.0,
    elapsed: 45.2,
    fps: 30.0,
    acquisitionTime: 0.23,
    trackingStability: 97,
  })

  useEffect(() => {
    // Try to connect to WebSocket, but don't fail if server not running
    try {
      const ws = new WebSocket('ws://localhost:8000/ws')
      
      ws.onmessage = (event) => {
        try {
          const telemetry = JSON.parse(event.data)
          setData(telemetry)
        } catch (e) {
          console.error('Failed to parse telemetry:', e)
        }
      }

      ws.onerror = () => console.log('WebSocket unavailable - using demo mode')
      ws.onclose = () => console.log('WebSocket closed')

      return () => ws.close()
    } catch (e) {
      console.log('WebSocket not available - running in demo mode')
    }
  }, [])

  return data
}
