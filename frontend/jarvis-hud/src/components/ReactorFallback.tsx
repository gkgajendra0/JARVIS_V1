import React from 'react';

/**
 * Stands in for the 3D scene when WebGL is unavailable or the context is lost.
 * Drawn with CSS so it needs no GPU, and styled to read as a deliberate
 * schematic view rather than a broken canvas.
 */
const ReactorFallback: React.FC<{ reason?: string }> = ({ reason }) => (
  <div className="absolute inset-0 z-10 flex items-center justify-center">
    <div className="flex flex-col items-center gap-6">
      <div className="relative h-56 w-56">
        <div className="absolute inset-0 rounded-full border border-[rgba(151,178,199,0.28)]" />
        <div className="absolute inset-[10%] rounded-full border border-[rgba(151,178,199,0.18)]" />
        <div className="absolute inset-[26%] rounded-full border border-[rgba(151,178,199,0.14)]" />

        {/* Winding marks around the housing. */}
        {Array.from({ length: 10 }, (_, i) => (
          <div
            key={i}
            className="absolute left-1/2 top-1/2 h-2 w-5 -translate-x-1/2 -translate-y-1/2 rounded-[1px] bg-[rgba(194,121,60,0.55)]"
            style={{ transform: `rotate(${(i / 10) * 360}deg) translateY(-6.4rem)` }}
          />
        ))}

        {/* Emitter. */}
        <div
          className="absolute left-1/2 top-1/2 h-16 w-16 -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{
            background:
              'radial-gradient(circle, rgba(200,228,244,0.9) 0%, rgba(132,182,214,0.35) 55%, transparent 75%)',
          }}
        />
      </div>

      <div className="max-w-xs text-center">
        <p className="etch">
          {reason?.startsWith('Low-GPU') ? 'Reactor schematic / low GPU' : 'Reactor visualisation offline'}
        </p>
        <p className="etch mt-2 !tracking-normal !text-[#dde4ea]/30">
          {reason ?? 'This browser has no WebGL support available.'} Live controls remain in
          the original JARVIS runtime.
        </p>
      </div>
    </div>
  </div>
);

export default ReactorFallback;
