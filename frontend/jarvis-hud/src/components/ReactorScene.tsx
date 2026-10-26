import React, { Suspense, useCallback, useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import * as THREE from 'three';
import ArcReactor, { ReactorState } from './ArcReactor';
import ErrorBoundary from './ErrorBoundary';
import ReactorFallback from './ReactorFallback';
import { isWebGLAvailable } from '../lib/webgl';

interface ReactorSceneProps {
  state: ReactorState;
  taskComplexity: number;
  audioLevel: number;
}

const ReactorScene: React.FC<ReactorSceneProps> = ({ state, taskComplexity, audioLevel }) => {
  // Checked before mounting: Three throws outright when it cannot create a
  // context, so a designed fallback beats relying on the error boundary.
  const [supported] = useState(isWebGLAvailable);
  const [contextLost, setContextLost] = useState(false);

  const handleCreated = useCallback(({ gl }: { gl: THREE.WebGLRenderer }) => {
    // Filmic response curve — highlights roll off instead of clipping to
    // flat white, which is most of what separates "lit" from "glowing".
    gl.toneMapping = THREE.ACESFilmicToneMapping;
    gl.toneMappingExposure = 1.05;
    gl.setClearColor('#000000', 0);

    // A driver reset or too many live contexts can take the canvas away after
    // it has already rendered. Swap to the fallback rather than freeze on a
    // dead canvas, and recover if the browser hands the context back.
    const canvas = gl.domElement;
    canvas.addEventListener('webglcontextlost', (event) => {
      event.preventDefault();
      console.warn('WebGL context lost — falling back to the static reactor.');
      setContextLost(true);
    });
    canvas.addEventListener('webglcontextrestored', () => {
      console.info('WebGL context restored.');
      setContextLost(false);
    });
  }, []);

  if (!supported) {
    return <ReactorFallback />;
  }

  if (contextLost) {
    return <ReactorFallback reason="The graphics context was lost." />;
  }

  return (
    <ErrorBoundary
      label="ReactorScene"
      fallback={<ReactorFallback reason="The 3D scene failed to start." />}
    >
      <div className="absolute inset-0 z-10 cursor-grab active:cursor-grabbing">
        {/* Bounce light on the backplate, sitting behind the canvas. */}
        <div className="absolute inset-0 backlight" />

        <Canvas
          dpr={[1, 1.5]}
          camera={{ position: [0, 0, 9], fov: 42 }}
          gl={{ antialias: true, alpha: true }}
          onCreated={handleCreated}
        >
          <Suspense fallback={null}>
            <ArcReactor state={state} taskComplexity={taskComplexity} audioLevel={audioLevel} />
            <ambientLight intensity={0.12} />
            <directionalLight position={[4, 6, 5]} intensity={0.6} color="#c3d4e0" />

            {/* The unit stays put; the camera orbits it. Panning is disabled so
                it can never be dragged out of frame, and damping gives the
                movement the weight of turning a real object over in your hands. */}
            <OrbitControls
              makeDefault
              enablePan={false}
              enableDamping
              dampingFactor={0.08}
              rotateSpeed={0.55}
              zoomSpeed={0.6}
              minDistance={5}
              maxDistance={16}
              minPolarAngle={Math.PI * 0.08}
              maxPolarAngle={Math.PI * 0.92}
            />
          </Suspense>
        </Canvas>
      </div>
    </ErrorBoundary>
  );
};

export default ReactorScene;
