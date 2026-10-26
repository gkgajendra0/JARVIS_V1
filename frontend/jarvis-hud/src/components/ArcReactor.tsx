import React, { useEffect, useLayoutEffect, useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Environment, Lightformer } from '@react-three/drei';
import { PointLight } from 'three';
import * as THREE from 'three';
import {
  MARK_I_BUNDLE_COUNT,
  getMarkIBraceAngles,
  getMarkICoilTransforms,
  getMarkIEmitterRings,
  getMarkIFastenerPositions,
} from '../markIReactor';

export type ReactorState = 'idle' | 'listening' | 'thinking' | 'speaking';

interface ArcReactorProps {
  state: ReactorState;
  taskComplexity: number;
  audioLevel: number;
}

const EMISSION_COLOR = {
  idle: new THREE.Color('#a5d7f0'),
  listening: new THREE.Color('#c5eeff'),
  thinking: new THREE.Color('#cbb17d'),
  speaking: new THREE.Color('#e2f7ff'),
} as const;

const LOAD_COLOR = new THREE.Color('#d19a70');
const FRONT_Z = 0.62;
const BACK_Z = -0.86;

/**
 * Cave-built Mark I: the hardware is stationary, with ten dense copper winding
 * packs on an iron former and a recessed, screened blue-white light source.
 * State drives the illumination only; there is no fictional spinning turbine.
 */
const ArcReactor: React.FC<ArcReactorProps> = ({ state, taskComplexity, audioLevel }) => {
  const keyLightRef = useRef<PointLight>(null);
  const targetIntensity = useRef(1.15);
  const windingRef = useRef<THREE.InstancedMesh>(null);

  const windings = useMemo(getMarkICoilTransforms, []);
  const fasteners = useMemo(getMarkIFastenerPositions, []);
  const emitterRings = useMemo(getMarkIEmitterRings, []);
  const braceAngles = useMemo(getMarkIBraceAngles, []);
  const coilGeometry = useMemo(() => new THREE.TorusGeometry(0.19, 0.022, 8, 20), []);
  const emitterMaterial = useMemo(
    () =>
      new THREE.MeshStandardMaterial({
        color: '#a7d0e7',
        emissive: EMISSION_COLOR.idle.clone(),
        emissiveIntensity: 1.15,
        metalness: 0.15,
        roughness: 0.28,
      }),
    [],
  );

  useEffect(() => {
    return () => {
      coilGeometry.dispose();
      emitterMaterial.dispose();
    };
  }, [coilGeometry, emitterMaterial]);

  // All 110 turns render in a single draw call; no per-frame matrix updates.
  useLayoutEffect(() => {
    if (!windingRef.current) return;
    const transform = new THREE.Object3D();
    windings.forEach(({ position, rotation }, index) => {
      transform.position.set(...position);
      transform.rotation.set(...rotation);
      transform.updateMatrix();
      windingRef.current?.setMatrixAt(index, transform.matrix);
    });
    windingRef.current.instanceMatrix.needsUpdate = true;
  }, [windings]);

  const emission = useMemo(
    () => EMISSION_COLOR[state].clone().lerp(LOAD_COLOR, Math.max(0, taskComplexity - 0.6) * 1.5),
    [state, taskComplexity],
  );

  useFrame((frame, delta) => {
    const t = frame.clock.getElapsedTime();
    const base =
      state === 'speaking' ? 2.3 : state === 'thinking' ? 1.95 : state === 'listening' ? 1.7 : 1.2;
    const modulation =
      state === 'speaking'
        ? Math.sin(t * 8) * 0.12 + Math.sin(t * 3) * 0.06
        : state === 'listening'
          ? audioLevel * 0.42
          : state === 'thinking'
            ? Math.sin(t * 2.4) * 0.1
            : Math.sin(t * 0.8) * 0.035;

    targetIntensity.current += (base + modulation - targetIntensity.current) * Math.min(1, delta * 5);
    emitterMaterial.emissiveIntensity = targetIntensity.current;
    emitterMaterial.emissive.lerp(emission, Math.min(1, delta * 4));
    if (keyLightRef.current) {
      keyLightRef.current.intensity = targetIntensity.current * 2.9;
      keyLightRef.current.color.lerp(emission, Math.min(1, delta * 4));
    }
  });

  return (
    <>
      {/* Local reflection environment: no runtime assets or texture requests. */}
      <Environment resolution={256}>
        <Lightformer intensity={5} position={[0, 5, 3]} scale={[10, 3, 1]} color="#ede9df" />
        <Lightformer intensity={2.5} position={[-6, -1, 2]} scale={[4, 6, 1]} color="#a5a19a" />
        <Lightformer intensity={1.7} position={[6, 1, -3]} scale={[4, 5, 1]} color="#b6ac9e" />
        <Lightformer intensity={1.2} position={[0, -5, 1]} scale={[8, 2, 1]} color="#77736d" />
        <Lightformer intensity={1.4} form="ring" position={[0, 0, 4]} scale={4} color="#8aacc0" />
        <Lightformer intensity={3} position={[0, 3, -6]} scale={[9, 4, 1]} color="#a6a9a9" />
        <Lightformer intensity={1.5} position={[-4, -2, -5]} scale={[5, 4, 1]} color="#717981" />
      </Environment>

      <group scale={0.66} position={[0, 0.35, 0]}>
        {/* Blackened steel barrel with machined edges and a recessed floor. */}
        <mesh position={[0, 0, (FRONT_Z + BACK_Z) / 2]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[3.16, 3.16, FRONT_Z - BACK_Z, 96, 1, true]} />
          <meshStandardMaterial color="#41484c" metalness={0.88} roughness={0.66} side={THREE.DoubleSide} />
        </mesh>
        <mesh position={[0, 0, BACK_Z + 0.12]} rotation={[Math.PI / 2, 0, 0]}>
          <cylinderGeometry args={[3.14, 3.14, 0.16, 96]} />
          <meshStandardMaterial color="#191f23" metalness={0.62} roughness={0.78} />
        </mesh>
        <mesh position={[0, 0, FRONT_Z]}>
          <torusGeometry args={[3.12, 0.16, 18, 96]} />
          <meshStandardMaterial color="#7c8283" metalness={0.94} roughness={0.42} envMapIntensity={1.2} />
        </mesh>
        <mesh position={[0, 0, FRONT_Z + 0.12]}>
          <torusGeometry args={[2.95, 0.035, 12, 96]} />
          <meshStandardMaterial color="#242b30" metalness={0.8} roughness={0.62} />
        </mesh>
        {[0.2, 0.62].map((t) => (
          <mesh key={`machined-band-${t}`} position={[0, 0, FRONT_Z - (FRONT_Z - BACK_Z) * t]}>
            <torusGeometry args={[3.18, 0.044, 12, 96]} />
            <meshStandardMaterial color="#676e71" metalness={0.9} roughness={0.47} />
          </mesh>
        ))}

        {/* Actual rear shell; the prop stays solid as the user orbits. */}
        <group position={[0, 0, BACK_Z]}>
          <mesh rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[3.16, 3.16, 0.14, 96]} />
            <meshStandardMaterial color="#42494e" metalness={0.9} roughness={0.63} />
          </mesh>
          <mesh position={[0, 0, -0.25]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[1.5, 1.9, 0.42, 64]} />
            <meshStandardMaterial color="#343c40" metalness={0.9} roughness={0.55} />
          </mesh>
          <mesh position={[0, 0, -0.5]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.62, 0.62, 0.2, 48]} />
            <meshStandardMaterial color="#666c6d" metalness={0.92} roughness={0.44} />
          </mesh>
          {Array.from({ length: 16 }, (_, i) => {
            const a = (i / 16) * Math.PI * 2;
            return (
              <mesh key={`back-bolt-${i}`} position={[Math.cos(a) * 2.65, Math.sin(a) * 2.65, -0.11]} rotation={[Math.PI / 2, 0, 0]}>
                <cylinderGeometry args={[0.07, 0.07, 0.09, 8]} />
                <meshStandardMaterial color="#8b9091" metalness={0.95} roughness={0.4} />
              </mesh>
            );
          })}
        </group>

        {/* Iron former, individual copper turns, black insulators and clamps. */}
        <mesh position={[0, 0, 0.05]}>
          <torusGeometry args={[2.46, 0.17, 14, 100]} />
          <meshStandardMaterial color="#30383a" metalness={0.76} roughness={0.68} />
        </mesh>
        {Array.from({ length: MARK_I_BUNDLE_COUNT }, (_, i) => {
          const angle = (i / MARK_I_BUNDLE_COUNT) * Math.PI * 2;
          return (
            <group key={`coil-mount-${i}`} rotation={[0, 0, angle]}>
              <mesh position={[2.46, 0, -0.15]}>
                <boxGeometry args={[0.5, 0.97, 0.12]} />
                <meshStandardMaterial color="#202a2d" metalness={0.5} roughness={0.81} />
              </mesh>
              {[-0.45, 0.45].map((offset) => (
                <mesh key={`clamp-${offset}`} position={[2.46, offset, 0.23]}>
                  <boxGeometry args={[0.48, 0.085, 0.18]} />
                  <meshStandardMaterial color="#7a7b73" metalness={0.88} roughness={0.53} />
                </mesh>
              ))}
            </group>
          );
        })}
        <instancedMesh ref={windingRef} args={[coilGeometry, undefined, windings.length]}>
            <meshStandardMaterial color="#b97536" metalness={0.94} roughness={0.3} envMapIntensity={1.6} />
        </instancedMesh>

        {/* Rivets and retaining screws: a physical, fixed front bezel. */}
        {fasteners.map(({ angle, position }, i) => (
          <group key={`face-screw-${i}`} position={position} rotation={[0, 0, angle]}>
            <mesh rotation={[Math.PI / 2, 0, 0]}>
              <cylinderGeometry args={[0.078, 0.078, 0.085, 10]} />
              <meshStandardMaterial color="#a0a5a3" metalness={0.94} roughness={0.34} />
            </mesh>
            <mesh position={[0, 0, 0.049]}>
              <boxGeometry args={[0.075, 0.014, 0.01]} />
              <meshStandardMaterial color="#32373a" metalness={0.7} roughness={0.62} />
            </mesh>
          </group>
        ))}

        {/* Layered stator around the emitter, with vent slots in dark steel. */}
        <mesh position={[0, 0, 0.11]}>
          <torusGeometry args={[2.07, 0.18, 18, 96]} />
          <meshStandardMaterial color="#5a6264" metalness={0.91} roughness={0.56} />
        </mesh>
        <mesh position={[0, 0, 0.19]}>
          <torusGeometry args={[1.94, 0.055, 12, 96]} />
          <meshStandardMaterial color="#171d21" metalness={0.8} roughness={0.61} />
        </mesh>
        {Array.from({ length: 24 }, (_, i) => {
          const a = (i / 24) * Math.PI * 2;
          return (
            <mesh key={`vent-${i}`} position={[Math.cos(a) * 2.08, Math.sin(a) * 2.08, 0.26]} rotation={[0, 0, a]}>
              <boxGeometry args={[0.22, 0.058, 0.075]} />
              <meshStandardMaterial color="#111a1e" metalness={0.4} roughness={0.82} />
            </mesh>
          );
        })}

        {/* Broad glowing annulus subdivided by dark front grille fins. */}
        <mesh position={[0, 0, 0.33]} material={emitterMaterial}>
          <ringGeometry args={[1.13, 1.87, 96]} />
        </mesh>
        {emitterRings.map((radius, i) => (
          <mesh key={`diffuser-${i}`} position={[0, 0, 0.42]} material={emitterMaterial}>
            <torusGeometry args={[radius, i === 0 ? 0.034 : 0.045, 12, 96]} />
          </mesh>
        ))}
        {Array.from({ length: 20 }, (_, i) => {
          const a = (i / 20) * Math.PI * 2;
          return (
            <mesh key={`grille-fin-${i}`} position={[Math.cos(a) * 1.51, Math.sin(a) * 1.51, 0.44]} rotation={[0, 0, a]}>
              <boxGeometry args={[0.72, 0.06, 0.07]} />
              <meshStandardMaterial color="#1e282e" metalness={0.85} roughness={0.52} />
            </mesh>
          );
        })}

        {/* Perforated-looking screen: fine crossed wires over a dim diffuser. */}
        <mesh position={[0, 0, 0.34]} material={emitterMaterial}>
          <circleGeometry args={[0.79, 64]} />
        </mesh>
        <mesh position={[0, 0, 0.39]}>
          <torusGeometry args={[0.8, 0.085, 12, 64]} />
          <meshStandardMaterial color="#68777c" metalness={0.92} roughness={0.48} />
        </mesh>
        {Array.from({ length: 11 }, (_, i) => {
          const offset = (i - 5) * 0.125;
          const chord = 2 * Math.sqrt(0.72 * 0.72 - offset * offset);
          return (
            <group key={`screen-grid-${i}`} position={[0, 0, 0.43]}>
              <mesh position={[0, offset, 0]}>
                <boxGeometry args={[chord, 0.023, 0.021]} />
                <meshStandardMaterial color="#354448" metalness={0.82} roughness={0.58} />
              </mesh>
              <mesh position={[offset, 0, 0]}>
                <boxGeometry args={[0.023, chord, 0.021]} />
                <meshStandardMaterial color="#354448" metalness={0.82} roughness={0.58} />
              </mesh>
            </group>
          );
        })}

        {/* Three fixed structural straps tie the emitter to the coil housing. */}
        {braceAngles.map((angle, i) => (
          <group key={`support-${i}`} rotation={[0, 0, angle]}>
            <mesh position={[1.64, 0, 0.59]}>
              <boxGeometry args={[1.52, 0.16, 0.15]} />
              <meshStandardMaterial color="#737c7b" metalness={0.93} roughness={0.47} />
            </mesh>
            <mesh position={[2.25, 0, 0.7]} rotation={[Math.PI / 2, 0, 0]}>
              <cylinderGeometry args={[0.105, 0.105, 0.1, 8]} />
              <meshStandardMaterial color="#a4aaa7" metalness={0.95} roughness={0.4} />
            </mesh>
            <mesh position={[1.0, 0, 0.7]} rotation={[Math.PI / 2, 0, 0]}>
              <cylinderGeometry args={[0.08, 0.08, 0.08, 8]} />
              <meshStandardMaterial color="#7a8384" metalness={0.94} roughness={0.4} />
            </mesh>
          </group>
        ))}

        {/* Only the emitter changes with JARVIS activity. */}
        <pointLight ref={keyLightRef} position={[0, 0, 0.97]} distance={9} decay={2} />
        <pointLight position={[0, 0, -0.6]} intensity={0.42} color="#6b9cb6" distance={5} decay={2} />
      </group>
    </>
  );
};

export default ArcReactor;
