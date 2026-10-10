import Phaser from 'phaser'

declare global {
  interface Window {
    __arena?: {
      call: string
      status: string
      scene: string
      phase: string
      winner: string | null
      banner: string
      sounds: number
    }
  }
}

export interface TablePaint {
  scene: string
  seats: { index: number; speaking: boolean; alive: boolean }[]
  count: number
}

export interface TableHandle {
  paint: (state: TablePaint) => void
  resize: () => void
  destroy: () => void
}

export function seatAnchor(index: number, count: number, width: number, height: number): { x: number; y: number } {
  const safe = Math.max(count, 1)
  const angle = -Math.PI / 2 + (index / safe) * Math.PI * 2
  return {
    x: width / 2 + Math.cos(angle) * width * 0.34,
    y: height / 2 + Math.sin(angle) * height * 0.3,
  }
}

class TableScene extends Phaser.Scene {
  private layer?: Phaser.GameObjects.Graphics
  private latest: TablePaint | null = null
  private reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches

  create(): void {
    this.layer = this.add.graphics()
    this.draw()
  }

  update(): void {
    if (this.reduce) {
      return
    }
    this.draw()
  }

  show(state: TablePaint | null): void {
    this.latest = state
    this.draw()
  }

  private draw(): void {
    const layer = this.layer
    if (!layer) {
      return
    }
    const width = this.scale.width
    const height = this.scale.height
    const night = this.latest?.scene === 'wolf_room' || this.latest?.scene === 'night'
    const wolves = this.latest?.scene === 'wolf_room'
    layer.clear()
    layer.fillStyle(0x14110e, 1)
    layer.fillRect(0, 0, width, height)
    layer.fillStyle(wolves ? 0x5a2424 : 0x3d291c, 1)
    layer.fillEllipse(width / 2, height / 2 + 8, width * 0.78, height * 0.72)
    layer.fillStyle(wolves ? 0x3a1818 : night ? 0x1a2420 : 0x243028, 1)
    layer.fillEllipse(width / 2, height / 2, width * 0.7, height * 0.62)
    layer.lineStyle(2, wolves ? 0x8c3a3a : 0x6b3e2a, 0.9)
    layer.strokeEllipse(width / 2, height / 2, width * 0.7, height * 0.62)
    const count = this.latest?.count ?? 0
    for (const seat of this.latest?.seats ?? []) {
      const point = seatAnchor(seat.index, count, width, height)
      if (seat.speaking) {
        layer.lineStyle(3, 0xd7b56d, 0.95)
        layer.strokeCircle(point.x, point.y, 40)
      }
      layer.fillStyle(seat.alive ? 0x1a120e : 0x2a211c, seat.alive ? 0.35 : 0.7)
      layer.fillCircle(point.x, point.y, 28)
    }
  }
}

export function mountTable(parent: HTMLElement): TableHandle {
  const scene = new TableScene()
  let current: TablePaint | null = null
  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    width: Math.max(parent.clientWidth, 320),
    height: Math.max(parent.clientHeight, 320),
    backgroundColor: '#14110e',
    banner: false,
    audio: { noAudio: true },
    scene,
  })
  return {
    paint(state) {
      current = state
      scene.show(state)
    },
    resize() {
      game.scale.resize(Math.max(parent.clientWidth, 320), Math.max(parent.clientHeight, 320))
      if (current) {
        scene.show(current)
      }
    },
    destroy() {
      game.destroy(true)
    },
  }
}
