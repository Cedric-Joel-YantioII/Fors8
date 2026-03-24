<template>
  <div ref="container" class="logo-3d-container"></div>
</template>

<script>
import { ref, onMounted, onUnmounted } from 'vue'
import * as THREE from 'three'

export default {
  name: 'Fors8Logo3D',
  props: {
    size: { type: Number, default: 400 },
  },
  setup(props) {
    const container = ref(null)
    let scene, camera, renderer, animationId
    let orbitalRings = []
    let agentDots = []
    let connectionLines = []
    let centerGlow

    function init() {
      const w = props.size
      const h = props.size

      scene = new THREE.Scene()

      camera = new THREE.PerspectiveCamera(45, w / h, 0.1, 1000)
      camera.position.set(0, 0, 6)

      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
      renderer.setSize(w, h)
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
      renderer.setClearColor(0x000000, 0)
      container.value.appendChild(renderer.domElement)

      // Ambient light
      scene.add(new THREE.AmbientLight(0x334155, 0.5))

      // Point lights
      const light1 = new THREE.PointLight(0x3b82f6, 2, 20)
      light1.position.set(3, 3, 5)
      scene.add(light1)

      const light2 = new THREE.PointLight(0x8b5cf6, 1.5, 20)
      light2.position.set(-3, -2, 4)
      scene.add(light2)

      // No center sphere — keep the text visible

      // Orbital rings
      const ringConfigs = [
        { radius: 2.0, tilt: [0.3, 0, 0], color: 0x3b82f6, opacity: 0.35, width: 1.5 },
        { radius: 2.3, tilt: [0.8, 0.5, 0], color: 0x6366f1, opacity: 0.25, width: 1 },
        { radius: 2.6, tilt: [-0.4, 0.3, 0.6], color: 0x8b5cf6, opacity: 0.2, width: 1 },
        { radius: 1.7, tilt: [1.2, 0, 0.3], color: 0x06b6d4, opacity: 0.15, width: 0.8 },
      ]

      ringConfigs.forEach(cfg => {
        const ringGeo = new THREE.RingGeometry(cfg.radius - 0.01, cfg.radius + 0.01, 128)
        const ringMat = new THREE.MeshBasicMaterial({
          color: cfg.color,
          transparent: true,
          opacity: cfg.opacity,
          side: THREE.DoubleSide,
        })
        const ring = new THREE.Mesh(ringGeo, ringMat)
        ring.rotation.set(...cfg.tilt)
        ring.userData = { baseRotation: [...cfg.tilt], speed: 0.001 + Math.random() * 0.002 }
        scene.add(ring)
        orbitalRings.push(ring)
      })

      // Agent dots (floating spheres on orbits)
      const dotConfigs = [
        { color: 0x3b82f6, size: 0.07, orbit: 2.0, speed: 0.008, phase: 0 },
        { color: 0x6366f1, size: 0.06, orbit: 2.3, speed: -0.006, phase: 1.5 },
        { color: 0x8b5cf6, size: 0.065, orbit: 2.6, speed: 0.005, phase: 3.0 },
        { color: 0xef4444, size: 0.08, orbit: 2.0, speed: -0.007, phase: 4.2 },
        { color: 0x22c55e, size: 0.055, orbit: 1.7, speed: 0.009, phase: 2.1 },
        { color: 0x06b6d4, size: 0.06, orbit: 2.3, speed: -0.004, phase: 5.0 },
        { color: 0xeab308, size: 0.05, orbit: 2.6, speed: 0.006, phase: 0.7 },
        { color: 0xf97316, size: 0.07, orbit: 1.7, speed: -0.008, phase: 3.8 },
      ]

      dotConfigs.forEach(cfg => {
        const dotGeo = new THREE.SphereGeometry(cfg.size, 16, 16)
        const dotMat = new THREE.MeshBasicMaterial({
          color: cfg.color,
          transparent: true,
          opacity: 0.9,
        })
        const dot = new THREE.Mesh(dotGeo, dotMat)
        dot.userData = { orbit: cfg.orbit, speed: cfg.speed, phase: cfg.phase, color: cfg.color }
        scene.add(dot)
        agentDots.push(dot)

        // Glow around each dot
        const glowDotGeo = new THREE.SphereGeometry(cfg.size * 2.5, 8, 8)
        const glowDotMat = new THREE.MeshBasicMaterial({
          color: cfg.color,
          transparent: true,
          opacity: 0.15,
        })
        const glowDot = new THREE.Mesh(glowDotGeo, glowDotMat)
        dot.add(glowDot)
      })

      // Connection lines between some dots
      const lineMat = new THREE.LineBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.12 })
      for (let i = 0; i < agentDots.length - 1; i++) {
        const lineGeo = new THREE.BufferGeometry()
        const positions = new Float32Array(6)
        lineGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
        const line = new THREE.Line(lineGeo, lineMat.clone())
        scene.add(line)
        connectionLines.push({ line, from: i, to: (i + 3) % agentDots.length })
      }

      // "FORS8" text plane (using canvas texture)
      const canvas = document.createElement('canvas')
      canvas.width = 512
      canvas.height = 128
      const ctx = canvas.getContext('2d')
      ctx.clearRect(0, 0, 512, 128)
      ctx.font = 'bold 72px "Space Grotesk", "Inter", sans-serif'
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      // Shadow
      ctx.fillStyle = 'rgba(0,0,0,0.08)'
      ctx.fillText('FORS8', 258, 66)
      // Main text
      ctx.fillStyle = '#0a0a0a'
      ctx.fillText('FORS8', 256, 64)
      // Subtitle
      ctx.font = '14px "JetBrains Mono", monospace'
      ctx.fillStyle = '#555555'
      ctx.fillText('WAR PREDICTION ENGINE', 256, 100)

      const textTexture = new THREE.CanvasTexture(canvas)
      textTexture.needsUpdate = true
      const textGeo = new THREE.PlaneGeometry(3.2, 0.8)
      const textMat = new THREE.MeshBasicMaterial({
        map: textTexture,
        transparent: true,
        side: THREE.DoubleSide,
      })
      const textMesh = new THREE.Mesh(textGeo, textMat)
      textMesh.position.z = 1.1
      scene.add(textMesh)
    }

    let time = 0
    function animate() {
      animationId = requestAnimationFrame(animate)
      time += 0.016

      // Rotate orbital rings slowly
      orbitalRings.forEach((ring, i) => {
        ring.rotation.z += ring.userData.speed
        ring.rotation.x = ring.userData.baseRotation[0] + Math.sin(time * 0.3 + i) * 0.05
      })

      // Move agent dots along orbits
      agentDots.forEach(dot => {
        const angle = time * dot.userData.speed * 10 + dot.userData.phase
        const r = dot.userData.orbit
        dot.position.x = Math.cos(angle) * r * (0.8 + Math.sin(angle * 0.5) * 0.2)
        dot.position.y = Math.sin(angle) * r * 0.4
        dot.position.z = Math.cos(angle * 0.7) * 0.5

        // Pulse opacity
        dot.material.opacity = 0.6 + Math.sin(time * 2 + dot.userData.phase) * 0.3
      })

      // Update connection lines
      connectionLines.forEach(({ line, from, to }) => {
        const posAttr = line.geometry.getAttribute('position')
        const a = agentDots[from]
        const b = agentDots[to]
        posAttr.setXYZ(0, a.position.x, a.position.y, a.position.z)
        posAttr.setXYZ(1, b.position.x, b.position.y, b.position.z)
        posAttr.needsUpdate = true

        // Fade lines based on distance
        const dist = a.position.distanceTo(b.position)
        line.material.opacity = Math.max(0, 0.15 - dist * 0.03)
      })

      // (no center sphere to pulse)

      // Gentle camera sway
      camera.position.x = Math.sin(time * 0.2) * 0.3
      camera.position.y = Math.cos(time * 0.15) * 0.2
      camera.lookAt(0, 0, 0)

      renderer.render(scene, camera)
    }

    onMounted(() => {
      init()
      animate()
    })

    onUnmounted(() => {
      if (animationId) cancelAnimationFrame(animationId)
      if (renderer) {
        renderer.dispose()
        if (container.value && renderer.domElement.parentNode === container.value) {
          container.value.removeChild(renderer.domElement)
        }
      }
    })

    return { container }
  }
}
</script>

<style scoped>
.logo-3d-container {
  width: 100%;
  display: flex;
  justify-content: center;
  align-items: center;
}
.logo-3d-container canvas {
  max-width: 100%;
  height: auto !important;
}
</style>
