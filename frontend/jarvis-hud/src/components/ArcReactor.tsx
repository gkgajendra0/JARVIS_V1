import React, { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Environment, Lightformer } from '@react-three/drei';
import { Group, Mesh, MeshStandardMaterial, PointLight } from 'three';
import * as THREE from 'three';

export type ReactorState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface ArcReactorProps {
  state: ReactorState;
  taskComplexity: number;
  audioLevel: number;
}

const EMISSION_COLOR = {
  idle: new THREE.Color('#7fb4d8'),
  listening: new THREE.Color('#9ed2f0'),
  thinking: new THREE.Color('#c9a86a'),
  speaking: new THREE.Color('#a8d8f5'),
} as const;

/* Heavy workloads bias the emitter toward a hot amber, the way a real device
   under load runs warmer. Blended, not switched, so the shift reads as strain. */
const LOAD_COLOR = new THREE.Color('#d08850');

/* Depth envelope of the housing. Everything internal is placed relative to
   these so the assembly stays a solid object from any viewing angle. */
const FRONT_Z = 0.62;
const BACK_Z = -0.86;

/* The winding sits on a former ring inside the barrel, recessed behind the
   bezel so you look *into* the device rather than at a decal on its face. */
const COIL_RING_RADIUS = 2.46;
const COIL_Z = 0.05;
const FORMER_TUBE = 0.15;

/* Housing plate: extruded with a bevel so its silhouette catches a real
   specular edge. Flat ShapeGeometry reads as paper under any lighting. */
function useSegmentGeometry(outer: number, waist: number, height: number) {
  return useMemo(() => {
    const shape = new THREE.Shape();
    shape.moveTo(-waist, 0);
    shape.lineTo(waist, 0);
    shape.lineTo(outer, height);
    shape.lineTo(-outer, height);
    shape.closePath();

    const geo = new THREE.ExtrudeGeometry(shape, {
      depth: 0.08,
      bevelEnabled: true,
      bevelThickness: 0.012,
      bevelSize: 0.012,
      bevelSegments: 2,
    });
    geo.center();
    return geo;
  }, [outer, waist, height]);
}

const ArcReactor: React.FC<ArcReactorProps> = ({ state, taskComplexity, audioLevel }) => {
  const groupRef = useRef<Group>(null);
  const shroudRef = useRef<Group>(null);
  const coreRef = useRef<Mesh>(null);
  const coreMatRef = useRef<MeshStandardMaterial>(null);
  const keyLightRef = useRef<PointLight>(null);

  const segmentGeometry = useSegmentGeometry(0.34, 0.2, 0.62);
  // Wire radius sits just proud of the former tube so each turn hugs the ring
  // it is wound on instead of hooping loosely around it.
  const coilGeometry = useMemo(
    () => new THREE.TorusGeometry(FORMER_TUBE + 0.038, 0.034, 10, 26),
    [],
  );

  // Ten bundles of five turns wrapped around the outer housing. Each turn's
  // axis is tangent to the ring, which is what makes it read as wound wire
  // rather than as loose rings floating near the housing.
  const coilTransforms = useMemo(() => {
    const turns: Array<{
      key: string;
      position: [number, number, number];
      rotation: [number, number, number];
    }> = [];

    for (let bundle = 0; bundle < 10; bundle++) {
      const centre = (bundle / 10) * Math.PI * 2;
      for (let turn = -2; turn <= 2; turn++) {
        const angle = centre + turn * 0.07;
        turns.push({
          key: `coil-${bundle}-${turn}`,
          position: [Math.cos(angle) * COIL_RING_RADIUS, Math.sin(angle) * COIL_RING_RADIUS, COIL_Z],
          rotation: [0, Math.PI / 2, angle + Math.PI / 2],
        });
      }
    }
    return turns;
  }, []);

  const emission = useMemo(
    () => EMISSION_COLOR[state].clone().lerp(LOAD_COLOR, Math.max(0, taskComplexity - 0.6) * 1.5),
    [state, taskComplexity],
  );
  const targetIntensity = useRef(1);

  useFrame((frame, delta) => {
    const t = frame.clock.getElapsedTime();

    // Slow, constant-rate rotation. Real machinery does not ease in and out.
    if (groupRef.current) groupRef.current.rotation.z = t * 0.06;
    if (shroudRef.current) shroudRef.current.rotation.z = -t * 0.11;

    // Output level is driven by state, then smoothed so transitions ramp like
    // a power supply settling rather than snapping between values.
    const base =
      state === 'speaking' ? 2.5 : state === 'thinking' ? 2.1 : state === 'listening' ? 1.8 : 1.15;
    const modulation =
      state === 'speaking'
        ? Math.sin(t * 9) * 0.18 + Math.sin(t * 3.1) * 0.1
        : state === 'listening'
          ? audioLevel * 0.5
          : state === 'thinking'
            ? Math.sin(t * 2.4) * 0.14
            : Math.sin(t * 0.9) * 0.05;

    targetIntensity.current += (base + modulation - targetIntensity.current) * Math.min(1, delta * 6);

    if (coreMatRef.current) {
      coreMatRef.current.emissiveIntensity = targetIntensity.current;
      coreMatRef.current.emissive.lerp(emission, Math.min(1, delta * 4));
    }
    if (keyLightRef.current) {
      keyLightRef.current.intensity = targetIntensity.current * 3.2;
      keyLightRef.current.color.lerp(emission, Math.min(1, delta * 4));
    }
    // Thermal swell only — a few percent, never a visible "bounce".
    if (coreRef.current) {
      coreRef.current.scale.setScalar(1 + (targetIntensity.current - 1.15) * 0.012);
    }
  });

  return (
    <>
      {/* Local IBL. Lightformers build the env map in-scene, so reflections are
          real and nothing is fetched from a CDN at runtime. */}
      <Environment resolution={256}>
        {/* Metal at metalness 1 has no diffuse colour of its own — every value
            you see is reflected environment, so these have to be genuinely
            bright or the housing renders as black. */}
        <Lightformer intensity={6} position={[0, 5, 3]} scale={[10, 3, 1]} color="#f0eee9" />
        <Lightformer intensity={2.6} position={[-6, -1, 2]} scale={[4, 6, 1]} color="#9c9a96" />
        <Lightformer intensity={2} position={[6, 1, -3]} scale={[4, 5, 1]} color="#b0aca6" />
        <Lightformer intensity={1.4} position={[0, -5, 1]} scale={[8, 2, 1]} color="#6b6862" />
        <Lightformer intensity={1.1} form="ring" position={[0, 0, 4]} scale={4} color="#7ea8c4" />
        {/* Rear fill — without a source behind it, orbiting round the back
            finds an unlit black disc, since metal only shows what it reflects. */}
        <Lightformer intensity={3.2} position={[0, 3, -6]} scale={[9, 4, 1]} color="#939ea8" />
        <Lightformer intensity={1.6} position={[-4, -2, -5]} scale={[5, 4, 1]} color="#6a7078" />
      </Environment>

      <group ref={groupRef} scale={0.54} position={[0, 0.35, 0]}>
        {/* Front bezel, sitting proud of the housing lip. */}
        <mesh position={[0, 0, FRONT_Z]}>
          <torusGeometry args={[3.1, 0.2, 24, 96]} />
          <meshStandardMaterial color="#9aa3ad" metalness={1} roughness={0.31} envMapIntensity={1.6} />
        </mesh>

        {/* Housing barrel. The device is a cylinder with real depth, not a
            disc — this wall is what you actually see when orbiting to the side. */}
        <mesh position={[0, 0, (FRONT_Z + BACK_Z) / 2]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[3.16, 3.16, FRONT_Z - BACK_Z, 96, 1, true]} />
          <meshStandardMaterial
            color="#7e858d"
            metalness={1}
            roughness={0.36}
            envMapIntensity={1.4}
            side={THREE.DoubleSide}
          />
        </mesh>

        {/* Machined relief bands around the barrel. */}
        {[0.22, 0.55].map((t) => (
          <mesh key={`band-${t}`} position={[0, 0, FRONT_Z - (FRONT_Z - BACK_Z) * t]}>
            <torusGeometry args={[3.19, 0.045, 12, 96]} />
            <meshStandardMaterial color="#5c636b" metalness={1} roughness={0.44} envMapIntensity={1.1} />
          </mesh>
        ))}

        {/* Recessed interior floor the shroud and emitter sit above. */}
        <mesh position={[0, 0, BACK_Z + 0.12]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[3.14, 3.14, 0.16, 96]} />
          <meshStandardMaterial color="#2a2e34" metalness={0.8} roughness={0.7} envMapIntensity={0.7} />
        </mesh>

        {/* Rear face: closing plate, mounting boss and bolt ring, so orbiting
            all the way round finds a finished back rather than a hollow shell. */}
        <group position={[0, 0, BACK_Z]}>
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[3.16, 3.16, 0.14, 96]} />
            <meshStandardMaterial color="#4a515a" metalness={0.95} roughness={0.52} envMapIntensity={1} />
          </mesh>
          <mesh position={[0, 0, -0.24]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[1.5, 1.9, 0.42, 64]} />
            <meshStandardMaterial color="#3f454d" metalness={1} roughness={0.46} envMapIntensity={1} />
          </mesh>
          <mesh position={[0, 0, -0.5]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.62, 0.62, 0.2, 48]} />
            <meshStandardMaterial color="#6d747c" metalness={1} roughness={0.34} envMapIntensity={1.3} />
          </mesh>
          {Array.from({ length: 16 }, (_, i) => {
            const angle = (i / 16) * Math.PI * 2;
            return (
              <mesh
                key={`bolt-${i}`}
                position={[Math.cos(angle) * 2.62, Math.sin(angle) * 2.62, -0.11]}
                rotation={[Math.PI / 2, 0, 0]}
              >
                <cylinderGeometry args={[0.075, 0.075, 0.09, 12]} />
                <meshStandardMaterial color="#8d949c" metalness={1} roughness={0.3} envMapIntensity={1.4} />
              </mesh>
            );
          })}
        </group>

        {/* Former ring carrying the winding. */}
        <mesh position={[0, 0, COIL_Z]}>
          <torusGeometry args={[COIL_RING_RADIUS, FORMER_TUBE, 16, 80]} />
          <meshStandardMaterial color="#40464e" metalness={1} roughness={0.45} envMapIntensity={1} />
        </mesh>

        {/* Copper windings — the detail that sells it as built hardware.
            Grouped into ten bundles of five turns, the way wire is actually
            wound onto a core, rather than spaced evenly like decoration. */}
        {coilTransforms.map(({ key, position, rotation }) => (
          <mesh key={key} geometry={coilGeometry} position={position} rotation={rotation}>
            <meshStandardMaterial
              color="#c2793c"
              metalness={1}
              roughness={0.38}
              envMapIntensity={1.5}
            />
          </mesh>
        ))}

        {/* Counter-rotating shroud of bevelled plates. */}
        <group ref={shroudRef}>
          {Array.from({ length: 12 }, (_, i) => {
            const angle = (i / 12) * Math.PI * 2;
            const radius = 1.72;
            return (
              <mesh
                key={`plate-${i}`}
                geometry={segmentGeometry}
                position={[Math.cos(angle) * radius, Math.sin(angle) * radius, 0.2]}
                rotation={[0, 0, angle - Math.PI / 2]}

              >
                <meshStandardMaterial
                  color="#8d949c"
                  metalness={1}
                  roughness={0.26}
                  envMapIntensity={1.5}
                />
              </mesh>
            );
          })}
        </group>

        {/* Containment ring around the emitter. */}
        <mesh position={[0, 0, 0.24]}>
          <torusGeometry args={[1.12, 0.075, 20, 80]} />
          <meshStandardMaterial color="#3d434b" metalness={1} roughness={0.3} envMapIntensity={1} />
        </mesh>

        {/* Emitter: the only genuinely bright surface in the whole scene.
            Tone mapping is left ON so the highlight rolls off filmically —
            bypassing it is what turns an emitter into a flat white disc. */}
        <mesh ref={coreRef} position={[0, 0, 0.2]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.92, 0.92, 0.1, 64]} />
          <meshStandardMaterial
            ref={coreMatRef}
            color="#0d1116"
            emissive={EMISSION_COLOR.idle}
            emissiveIntensity={1.15}
            metalness={0.2}
            roughness={0.22}
          />
        </mesh>

        {/* Emitter grille: dark spokes and a hub occluding the plasma face, so
            it reads as a structured aperture instead of a glowing hole. */}
        <group position={[0, 0, 0.3]}>
          {/* Bars stop short of the hub — full-width spokes would overlap each
              other at the centre and z-fight into a dark cross. */}
          {Array.from({ length: 12 }, (_, i) => {
            const angle = (i / 12) * Math.PI * 2;
            const midpoint = 0.58;
            return (
              <mesh
                key={`spoke-${i}`}
                position={[Math.cos(angle) * midpoint, Math.sin(angle) * midpoint, 0]}
                rotation={[0, 0, angle]}
              >
                <boxGeometry args={[0.58, 0.035, 0.02]} />
                <meshStandardMaterial color="#232a31" metalness={0.95} roughness={0.4} />
              </mesh>
            );
          })}
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.2, 0.2, 0.05, 32]} />
            <meshStandardMaterial color="#2a323a" metalness={1} roughness={0.32} envMapIntensity={1.4} />
          </mesh>
          {/* No rotation: a torus already lies in the XY plane. Turning it 90°
              about X puts it edge-on to the camera and it renders as a line. */}
          <mesh>
            <torusGeometry args={[0.55, 0.03, 12, 48]} />
            <meshStandardMaterial color="#242b33" metalness={1} roughness={0.35} />
          </mesh>
        </group>

        {/* Diffuser glass over the emitter. */}
        <mesh position={[0, 0, 0.37]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[0.98, 0.98, 0.02, 64]} />
          <meshPhysicalMaterial
            color="#c6dced"
            transmission={0.95}
            thickness={0.3}
            roughness={0.14}
            ior={1.45}
            transparent
            opacity={0.35}
          />
        </mesh>

        {/* Light thrown by the emitter onto its own housing. */}
        <pointLight ref={keyLightRef} position={[0, 0, 1.1]} distance={9} decay={2} />
        <pointLight position={[0, 0, -0.6]} intensity={0.5} color="#4d7891" distance={5} decay={2} />
      </group>
    </>
  );
};

export default ArcReactor;
