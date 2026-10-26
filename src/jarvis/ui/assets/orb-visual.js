"use strict";
/**
 * Procedural, fully offline, read-only JARVIS energy core.
 * Cinematic 3D illusion in Canvas2D; no WebGL dependency, no generated imagery,
 * no remote resources, no access to microphone/audio/camera/user data.
 * Purely decorative movement follows the already-authorized voice lifecycle.
 */
(function installOrbVisual() {
  const TAU = Math.PI * 2;
  const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
  const clamp = (value, lo, hi) => Math.max(lo, Math.min(hi, value));
  const sphereCloud = [];
  for (let i = 0; i < 690; i++) {
    const y = 1 - 2 * (i + .5) / 690;
    const ring = Math.sqrt(Math.max(0, 1 - y * y));
    const a = GOLDEN_ANGLE * i;
    sphereCloud.push([Math.cos(a) * ring, y, Math.sin(a) * ring, i]);
  }
  const sparks = Array.from({length: 126}, (_, i) => {
    const seed = (i * 7919 + 73) % 1009;
    return {
      theta: i * GOLDEN_ANGLE,
      orbit: .73 + (seed % 43) / 92,
      pace: (i % 2 ? -1 : 1) * (.027 + (i % 11) * .009),
      radius: .7 + (i % 5) * .27,
      phase: seed / 27
    };
  });

  function roundRect(ctx, x, y, w, h, rad) {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, rad);
    ctx.fill();
  }

  function arcSegment(ctx, x, y, r, start, sweep, color, width, blur = 0) {
    ctx.beginPath();
    ctx.arc(x, y, r, start, start + sweep);
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    if (blur) {
      ctx.shadowBlur = blur;
      ctx.shadowColor = color;
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
  }

  class OrbVisual {
    constructor(ctx) {
      this.ctx = ctx;
      this.lastPointer = [0, 0];
    }

    draw({time: t, width: w, height: h, state, quality, projecting, reduced}) {
      const ctx = this.ctx;
      const cx = w / 2;
      const cy = h / 2;
      const radius = Math.min(w, h) * .345;
      const isSpeaking = state === "speaking";
      const isListening = state === "listening";
      const isThinking = state === "thinking";
      const activated = isSpeaking || isListening || isThinking || projecting;
      const pulse = reduced ? 1 : Math.sin(t * (isSpeaking ? 2.9 : 1.12)) * .018;
      const energy = (isSpeaking ? 1.24 : isThinking ? 1.16 : isListening ? 1.11 : 1) +
        (projecting ? .32 : 0);
      const alive = reduced ? 0 : t;
      const rotation = alive * (isThinking ? .30 : .125);
      const tilt = -.30 + (reduced ? 0 : Math.sin(t * .15) * .12);
      const c = Math.cos(rotation), s = Math.sin(rotation);
      const ct = Math.cos(tilt), st = Math.sin(tilt);
      const cyan = isThinking ? [166, 137, 255] : [84, 215, 255];
      const spectrum = (alpha) =>
        "rgba(" + cyan[0] + "," + cyan[1] + "," + cyan[2] + "," +
        clamp(alpha, 0, 1).toFixed(3) + ")";
      const density = quality === "eco" ? .32 : quality === "balanced" ? .67 : 1;

      ctx.clearRect(0, 0, w, h);
      if (w < 5 || h < 5) return;
      ctx.save();
      ctx.lineCap = "round";

      // Three-stage aura; this sells scale while leaving the orb dark in its
      // interior. Low-alpha additive lighting prevents an overexposed white disc.
      ctx.globalCompositeOperation = "screen";
      for (const [scale, alpha] of [
        [1.39, .16 * energy],
        [1.12, .24 * energy],
        [.79, .20 * energy]
      ]) {
        const glow = ctx.createRadialGradient(cx, cy, radius * .19, cx, cy, radius * scale);
        glow.addColorStop(0, "rgba(3,25,70,0)");
        glow.addColorStop(.54, spectrum(alpha * .65));
        glow.addColorStop(.84, spectrum(alpha * .21));
        glow.addColorStop(1, "rgba(0,115,255,0)");
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(cx, cy, radius * scale, 0, TAU);
        ctx.fill();
      }
      ctx.globalCompositeOperation = "source-over";

      // Volumetric shadowed core. No flat opaque cyan fill: the deep central
      // region remains blue-black while light hugs the curved edge.
      const body = ctx.createRadialGradient(
        cx - radius * .32, cy - radius * .37, radius * .025,
        cx + radius * .09, cy + radius * .08, radius * 1.07
      );
      body.addColorStop(0, "rgba(20,105,185,.86)");
      body.addColorStop(.24, "rgba(6,46,103,.94)");
      body.addColorStop(.48, "rgba(3,20,52,.97)");
      body.addColorStop(.77, "rgba(2,11,33,.985)");
      body.addColorStop(.92, "rgba(7,31,70,.97)");
      body.addColorStop(1, spectrum(.68 * energy));
      ctx.fillStyle = body;
      ctx.beginPath();
      ctx.arc(cx, cy, radius * (1 + pulse), 0, TAU);
      ctx.fill();

      // Clip all light filaments to the actual spherical surface.
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, radius * .985, 0, TAU);
      ctx.clip();
      ctx.globalCompositeOperation = "screen";

      function spherePoint(x, y, z) {
        const xr = x * c + z * s;
        const zr = z * c - x * s;
        const yr = y * ct - zr * st;
        const depth = y * st + zr * ct;
        return [cx + xr * radius, cy + yr * radius, depth];
      }

      // Far hemisphere latitude/longitude traces first, with depth-based
      // occlusion. Curved meridians provide the impression of actual rotation.
      const latitudes = quality === "eco" ? 7 : 14;
      const meridians = quality === "eco" ? 9 : quality === "balanced" ? 14 : 19;
      const steps = quality === "eco" ? 35 : 74;
      for (let layer = 0; layer < 2; layer++) {
        const foreground = layer === 1;
        for (let ring = 1; ring < latitudes; ring++) {
          const latitude = -Math.PI / 2 + ring * Math.PI / latitudes;
          const y = Math.sin(latitude);
          const rr = Math.cos(latitude);
          for (let k = 0; k < steps; k++) {
            const a = k * TAU / steps + Math.sin(t * .5 + ring) * .006;
            const b = (k + 1) * TAU / steps + Math.sin(t * .5 + ring) * .006;
            const p = spherePoint(rr * Math.cos(a), y, rr * Math.sin(a));
            const q = spherePoint(rr * Math.cos(b), y, rr * Math.sin(b));
            const front = (p[2] + q[2]) > 0;
            if (front !== foreground) continue;
            ctx.strokeStyle = front ? spectrum(.11 + .10 * energy) : "rgba(104,103,214,.075)";
            ctx.lineWidth = front ? .79 : .53;
            ctx.beginPath();
            ctx.moveTo(p[0], p[1]);
            ctx.lineTo(q[0], q[1]);
            ctx.stroke();
          }
        }
        for (let mer = 0; mer < meridians; mer++) {
          const lon = mer * TAU / meridians;
          for (let k = 0; k < steps; k++) {
            const lat1 = -Math.PI / 2 + k * Math.PI / steps;
            const lat2 = -Math.PI / 2 + (k + 1) * Math.PI / steps;
            const p = spherePoint(
              Math.cos(lat1) * Math.cos(lon), Math.sin(lat1),
              Math.cos(lat1) * Math.sin(lon)
            );
            const q = spherePoint(
              Math.cos(lat2) * Math.cos(lon), Math.sin(lat2),
              Math.cos(lat2) * Math.sin(lon)
            );
            const front = p[2] + q[2] > 0;
            if (front !== foreground) continue;
            ctx.strokeStyle = front ? spectrum(.17 + .06 * energy) : "rgba(91,103,181,.065)";
            ctx.lineWidth = front ? .72 : .5;
            ctx.beginPath();
            ctx.moveTo(p[0], p[1]); ctx.lineTo(q[0], q[1]); ctx.stroke();
          }
        }
      }

      // Asymmetric curved energy streams flow inside the sphere. Their varying
      // bands simulate turbulent plasma, not a uniform sonar grid.
      const streams = quality === "eco" ? 4 : quality === "balanced" ? 8 : 13;
      for (let band = 0; band < streams; band++) {
        const phase = band * 2.39996;
        const amplitude = radius * (.18 + band % 4 * .095);
        ctx.beginPath();
        for (let step = 0; step <= 110; step++) {
          const x = cx + ((step / 110) * 2 - 1) * radius;
          const norm = (x - cx) / radius;
          const envelope = Math.sqrt(Math.max(0, 1 - norm * norm));
          const y = cy + envelope * (
            Math.sin(norm * 7 + phase + alive * (.41 + band * .015)) * amplitude * .27 +
            Math.sin(norm * 3 - phase * .6 + alive * -.21) * amplitude * .42
          );
          if (step === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = band % 5 === 0 ?
          "rgba(166,117,251,.30)" : spectrum(.065 + (band % 3) * .037);
        ctx.lineWidth = band % 5 === 0 ? 1.25 : .68;
        ctx.stroke();
      }

      // Depth-aware 3D point cloud: back points dim, bright near hemisphere.
      const stride = quality === "eco" ? 4 : quality === "balanced" ? 2 : 1;
      for (let i = 0; i < sphereCloud.length; i += stride) {
        const [x, y, z, id] = sphereCloud[i];
        const p = spherePoint(x, y, z);
        const depth = (p[2] + 1) / 2;
        const flicker = .72 + .28 * Math.sin(alive * (1.1 + id % 4 * .26) + id * 1.17);
        ctx.fillStyle = id % 11 === 0 ?
          "rgba(192,137,255," + (.09 + depth * .62 * flicker).toFixed(3) + ")" :
          spectrum((.045 + depth * depth * .66) * flicker);
        const size = (.39 + depth * (id % 13 === 0 ? 1.6 : .78)) * (w > 450 ? 1.12 : 1);
        ctx.beginPath();
        ctx.arc(p[0], p[1], size, 0, TAU);
        ctx.fill();
      }
      ctx.restore();

      // Specular curved rim, with a chromatic second crescent.
      ctx.save();
      ctx.globalCompositeOperation = "screen";
      arcSegment(ctx, cx, cy, radius * .997, -2.18 + alive * .022,
        Math.PI * .96, spectrum(.26 + .27 * energy), 2.2, 9);
      arcSegment(ctx, cx, cy, radius * 1.002, .23 + alive * -.018,
        Math.PI * .47, "rgba(144,115,255,.37)", 1.2, 6);

      // Holographic gyroscope rings and rotating sector markings.
      for (let n = 0; n < 4; n++) {
        const r = radius * (1.065 + n * .085);
        const start = alive * (n % 2 ? -.11 : .085) + n * 1.57;
        arcSegment(ctx, cx, cy, r, start, Math.PI * (.25 + n * .07),
          n === 2 ? "rgba(161,118,255,.50)" : spectrum(.35 - n * .038),
          n === 0 ? 2.15 : 1.05, n === 0 ? 10 : 0);
        arcSegment(ctx, cx, cy, r, start + Math.PI * 1.13, Math.PI * .09,
          spectrum(.12 + n * .045), .85);
      }

      // Tilted, off-axis orbit ellipses with bright traveling satellites.
      if (quality !== "eco") {
        for (let i = 0; i < 3; i++) {
          ctx.save();
          ctx.translate(cx, cy);
          ctx.rotate(i * 1.13 - .26 + alive * (i % 2 ? -.03 : .025));
          ctx.scale(1, .26 + i * .105);
          ctx.beginPath();
          ctx.ellipse(0, 0, radius * (1.13 + i * .075),
            radius * (1.13 + i * .075), 0, 0, TAU);
          ctx.strokeStyle = i === 1 ? "rgba(158,116,249,.32)" : spectrum(.21 + i * .055);
          ctx.lineWidth = 1.05;
          ctx.stroke();
          ctx.restore();
        }
      }
      // Radial ticks provide the mechanical AR-reticle detail at large sizes.
      const tickCount = quality === "eco" ? 24 : 80;
      for (let i = 0; i < tickCount; i++) {
        const a = TAU * i / tickCount + .11;
        const inner = radius * (1.23 + (i % 5 === 0 ? -.017 : 0));
        const outer = inner + radius * (i % 10 === 0 ? .052 : .019);
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * inner, cy + Math.sin(a) * inner);
        ctx.lineTo(cx + Math.cos(a) * outer, cy + Math.sin(a) * outer);
        ctx.lineWidth = i % 10 === 0 ? 1.35 : .7;
        ctx.strokeStyle = i % 10 === 0 ? spectrum(.5) : spectrum(.13);
        ctx.stroke();
      }

      // Only a few sparks are actually glowing, so quality presets bound the
      // shadow/filter work and conserve the GPU for concurrent Jarvis vision.
      const sparse = quality === "eco" ? 9 : quality === "balanced" ? 38 : sparks.length;
      for (let i = 0; i < sparse; i++) {
        const p = sparks[i];
        const angle = p.theta + alive * p.pace;
        const x = cx + Math.cos(angle) * radius * p.orbit;
        const y = cy + Math.sin(angle * 1.11 + p.phase) * radius * (.3 + p.orbit * .58);
        const flicker = .48 + .52 * Math.sin(alive * 2.4 + p.phase);
        const dot = p.radius * (.6 + flicker * .6);
        ctx.fillStyle = i % 9 === 0 ?
          "rgba(198,169,255,.73)" : spectrum(.18 + .59 * flicker);
        ctx.beginPath();ctx.arc(x, y, dot, 0, TAU);ctx.fill();
      }

      // Central singularity remains small and bright, not a giant glowing dot.
      const singular = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * .34);
      singular.addColorStop(0, spectrum(.6 * energy));
      singular.addColorStop(.09, spectrum(.33 * energy));
      singular.addColorStop(.55, "rgba(22,92,214,.09)");
      singular.addColorStop(1, "rgba(1,20,58,0)");
      ctx.fillStyle = singular;
      ctx.beginPath();ctx.arc(cx, cy, radius * .35, 0, TAU);ctx.fill();

      if (activated) {
        const k = Math.min(1, energy / 1.5);
        ctx.beginPath();
        ctx.arc(cx, cy, radius * (1.31 + (reduced ? 0 : .027 * Math.sin(t * 2.3))), 0, TAU);
        ctx.strokeStyle = spectrum(.08 + k * .13);
        ctx.lineWidth = projecting ? 2.4 : 1;
        ctx.stroke();
      }
      ctx.restore();
    }
  }

  Object.defineProperty(window, "JarvisOrbVisual", {
    value: Object.freeze({
      create: (ctx) => new OrbVisual(ctx),
      version: "2.0-cinematic"
    }),
    writable: false, configurable: false
  });
})();
