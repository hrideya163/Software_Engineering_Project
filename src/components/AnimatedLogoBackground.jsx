import { Compass } from 'lucide-react'
import { useEffect, useRef } from 'react'

// This intentionally reuses the same Compass component used by Navbar.jsx.
export default function AnimatedLogoBackground() {
  const logoRef = useRef(null)

  useEffect(() => {
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (reduceMotion.matches) return undefined

    let frame
    let targetX = 0
    let targetY = 0
    let currentX = 0
    let currentY = 0

    const onMove = ({ clientX, clientY }) => {
      targetX = (clientX / window.innerWidth - 0.5) * 18
      targetY = (clientY / window.innerHeight - 0.5) * 14
    }
    const animate = () => {
      currentX += (targetX - currentX) * 0.035
      currentY += (targetY - currentY) * 0.035
      if (logoRef.current) logoRef.current.style.transform = `translate3d(${currentX}px, ${currentY}px, 0)`
      frame = requestAnimationFrame(animate)
    }

    window.addEventListener('pointermove', onMove, { passive: true })
    frame = requestAnimationFrame(animate)
    return () => {
      window.removeEventListener('pointermove', onMove)
      cancelAnimationFrame(frame)
    }
  }, [])

  return <div className="animated-logo-background" aria-hidden="true">
    <div ref={logoRef} className="animated-logo-parallax">
      <div className="animated-logo-rotation">
        <Compass strokeWidth={1.05} />
      </div>
    </div>
  </div>
}
