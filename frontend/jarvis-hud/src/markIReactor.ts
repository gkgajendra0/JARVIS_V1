/** Procedural Mk I prop layout shared by the WebGL unit and CSS schematic. */
export const MARK_I_BUNDLE_COUNT = 10;
export const MARK_I_TURNS_PER_BUNDLE = 11;
export const MARK_I_COIL_RADIUS = 2.46;
export const MARK_I_COIL_Z = 0.05;

/** Bright annular channels around a darker, perforated central aperture. */
export function getMarkIEmitterRings(): number[] {
  return [0.96, 1.23, 1.55, 1.82];
}

/** Three stationary load-bearing straps, not a decorative spinning rotor. */
export function getMarkIBraceAngles(): number[] {
  return [0, (Math.PI * 2) / 3, (Math.PI * 4) / 3];
}

type Vector3Tuple = [number, number, number];

export interface CoilTurn {
  bundleIndex: number;
  turnIndex: number;
  angle: number;
  position: Vector3Tuple;
  rotation: Vector3Tuple;
}

export interface Fastener {
  angle: number;
  position: Vector3Tuple;
}

/** Separate bundles with visibly dense turns of copper around their formers. */
export function getMarkICoilTransforms(): CoilTurn[] {
  const turns: CoilTurn[] = [];
  for (let bundleIndex = 0; bundleIndex < MARK_I_BUNDLE_COUNT; bundleIndex++) {
    const centre = (bundleIndex / MARK_I_BUNDLE_COUNT) * Math.PI * 2;
    for (let turnIndex = 0; turnIndex < MARK_I_TURNS_PER_BUNDLE; turnIndex++) {
      const angle = centre + (turnIndex - (MARK_I_TURNS_PER_BUNDLE - 1) / 2) * 0.027;
      turns.push({
        bundleIndex,
        turnIndex,
        angle,
        position: [Math.cos(angle) * MARK_I_COIL_RADIUS, Math.sin(angle) * MARK_I_COIL_RADIUS, MARK_I_COIL_Z],
        rotation: [0, Math.PI / 2, angle + Math.PI / 2],
      });
    }
  }
  return turns;
}

/** Two flush screw heads between every coil pack's retaining brackets. */
export function getMarkIFastenerPositions(): Fastener[] {
  return Array.from({ length: MARK_I_BUNDLE_COUNT * 2 }, (_, index) => {
    const angle = ((index + 0.5) / (MARK_I_BUNDLE_COUNT * 2)) * Math.PI * 2;
    return { angle, position: [Math.cos(angle) * 3.06, Math.sin(angle) * 3.06, 0.74] };
  });
}
