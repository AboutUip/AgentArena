let context: AudioContext | null = null
let muted = false
let played = 0

export function soundMuted(): boolean {
  return muted
}

export function setSoundMuted(value: boolean): void {
  muted = value
}

export function soundsPlayed(): number {
  return played
}

function audio(): AudioContext | null {
  if (muted) {
    return null
  }
  const Construct = window.AudioContext
  if (!Construct) {
    return null
  }
  if (!context) {
    context = new Construct()
  }
  void context.resume()
  return context
}

function tone(frequency: number, delay: number, duration: number, type: OscillatorType, amount: number): void {
  const current = audio()
  if (!current) {
    return
  }
  const osc = current.createOscillator()
  const amp = current.createGain()
  const start = current.currentTime + delay
  osc.type = type
  osc.frequency.setValueAtTime(frequency, start)
  amp.gain.setValueAtTime(amount, start)
  amp.gain.exponentialRampToValueAtTime(0.001, start + duration)
  osc.connect(amp)
  amp.connect(current.destination)
  osc.start(start)
  osc.stop(start + duration)
  played += 1
}

export function playNight(): void {
  tone(196, 0, 0.42, 'sine', 0.05)
  tone(147, 0.16, 0.5, 'sine', 0.04)
}

export function playDay(): void {
  tone(392, 0, 0.2, 'sine', 0.045)
  tone(523, 0.12, 0.32, 'sine', 0.04)
}

export function playWolf(): void {
  tone(98, 0, 0.36, 'triangle', 0.05)
}

export function playSpeak(): void {
  tone(680, 0, 0.08, 'sine', 0.028)
}
