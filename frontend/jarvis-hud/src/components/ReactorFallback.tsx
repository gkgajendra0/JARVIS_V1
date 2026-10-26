import React from 'react';
import { MARK_I_BUNDLE_COUNT, getMarkIBraceAngles } from '../markIReactor';

/**
 * Stands in for the 3D scene when WebGL is unavailable or the context is lost.
 * Drawn with CSS so it needs no GPU, and styled to read as a deliberate
 * schematic view rather than a broken canvas.
 */
const ReactorFallback: React.FC<{ reason?: string }> = ({ reason }) => (
  <div className="absolute inset-0 z-10 flex items-center justify-center">
    <div className="flex flex-col items-center gap-6">
      <div className="relative h-64 w-64" role="img" aria-label="Mark I arc reactor schematic with ten copper coil packs">
        {/* Layered iron shell and recessed copper former. */}
        <div className="absolute inset-[3%] rounded-full border-[9px] border-[#727d81] bg-[radial-gradient(circle,#070f14_0%,#121e24_55%,#343d40_87%,#0d1418_100%)] shadow-[0_10px_28px_rgba(0,0,0,0.7),inset_0_0_0_3px_#252e32,inset_0_0_20px_#03090d]" />
        <div className="absolute inset-[10%] rounded-full border-[5px] border-[#313b3f]" />
        <div className="absolute inset-[17%] rounded-full border-2 border-[#667275]/70" />

        {/* Individual copper-wire turns, not just one stripe per coil. */}
        {Array.from({ length: MARK_I_BUNDLE_COUNT }, (_, i) => (
          <div
            key={i}
            className="absolute left-1/2 top-1/2 h-8 w-[23px] rounded-[2px] border-y-2 border-[#a5a39b] shadow-[0_1px_6px_rgba(0,0,0,0.8)]"
            style={{
              background: 'repeating-linear-gradient(90deg,#77411e 0px,#db9b55 2px,#a55d28 3px,#55391f 4px)',
              transform: `translate(-50%,-50%) rotate(${(i / MARK_I_BUNDLE_COUNT) * 360}deg) translateY(-5.73rem)`,
            }}
          />
        ))}

        {/* Bright annular light and a perforated-looking inner grille. */}
        <div
          className="absolute inset-[29%] rounded-full border-[7px] border-[#a9def6] shadow-[0_0_22px_#73b9ddaa,inset_0_0_16px_#a9e8ffbb]"
          style={{
            background:
              'radial-gradient(circle,#6cabc9 0%,#b7e9fc 35%,#6da8ca 59%,#12252e 78%,#19353f 100%)',
          }}
        />
        <div
          className="absolute inset-[37%] rounded-full border-[3px] border-[#59696e] shadow-[inset_0_0_14px_#a5e3ff]"
          style={{
            background:
              'repeating-linear-gradient(0deg,transparent 0px,transparent 4px,#344e5a 4px,#344e5a 6px),repeating-linear-gradient(90deg,transparent 0px,transparent 4px,#344e5a 4px,#344e5a 6px),#83c3df',
          }}
        />

        {/* Fixed structural ties from the aperture to the housing. */}
        {getMarkIBraceAngles().map((angle, i) => (
          <div
            key={i}
            className="absolute left-1/2 top-1/2 h-[7px] w-[76px] rounded-sm border-y border-[#a7b1ae] bg-[#606d70] shadow-[0_2px_3px_#000c]"
            style={{
              transform: `translate(0,-50%) rotate(${(angle * 180) / Math.PI}deg)`,
              transformOrigin: 'left center',
            }}
          />
        ))}
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
